from __future__ import annotations
import time
import json
import hashlib
import threading
from typing import Optional, Dict, Any, Callable
import requests
from .config import Config
from .macro import OrderMacro

def _hash_payload(p: Any) -> str:
    try:
        s = json.dumps(p, sort_keys=True, ensure_ascii=False)
    except Exception:
        s = str(p)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

class OrdersClient:
    """
    Polls ORDERS_URL for JSON like:
      - [{ "name": "...", "count": 1 }, ...]
      - or { "type": "final", "items": [ ... ] }
    Deduplicates by content hash and triggers macro.perform(items).
    """
    def __init__(self, cfg: Config, macro: OrderMacro, on_server_stop: Optional[Callable[[], None]] = None):
        self.cfg = cfg
        self.macro = macro
        self.on_server_stop = on_server_stop
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self.last_hash: Optional[str] = None
        
        # 오버레이 참조 (나중에 설정)
        self.overlay = None

    def set_overlay(self, overlay):
        """오버레이 참조 설정"""
        self.overlay = overlay

    def _extract_items(self, payload) -> Optional[list]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            if payload.get("type") == "final" and isinstance(payload.get("items"), list):
                return payload["items"]
            # fallback: if dict looks like order
            if "name" in payload or "menu" in payload:
                return [payload]
        return None

    def _tick(self):
        while self.running:
            try:
                # 주문 확인
                r = requests.get(self.cfg.orders_url, timeout=2)
                if r.status_code == 204:
                    time.sleep(self.cfg.orders_poll_interval_sec)
                    continue
                r.raise_for_status()
                payload = r.json()
                items = self._extract_items(payload)
                if items:
                    print("[ORDERS] new items:", items)
                    # 주문 처리 시작 - 마이크 종료 방지
                    if self.overlay:
                        self.overlay.set_processing_order(True)
                    try:
                        # 매크로 실행
                        self.macro.perform(items)
                        print("[ORDERS] 주문 처리 완료")
                    except Exception as e:
                        print(f"[ERR] 주문 처리 실패: {e}")
                    finally:
                        # 주문 처리 완료 - 마이크 종료 가능
                        if self.overlay:
                            self.overlay.set_processing_order(False)
                    # 동일한 주문이 다시 오더라도(새 POST) 처리 가능하도록 해시 메모리 초기화
                    self.last_hash = None
                else:
                    # optional: stop signal
                    if isinstance(payload, dict) and payload.get("type") == "stop" and self.on_server_stop:
                        print("[ORDERS] 서버에서 중지 신호 수신")
                        self.on_server_stop()
                
                # 마이크 펄스 상태 확인 (별도 요청)
                try:
                    pulse_r = requests.get(f"{self.cfg.orders_url.replace('/api/orders', '/api/mic-pulse')}", timeout=1)
                    if pulse_r.status_code == 200:
                        pulse_payload = pulse_r.json()
                        if "mic_pulse_enabled" in pulse_payload and self.overlay:
                            self.overlay.enable_mic_pulse(pulse_payload["mic_pulse_enabled"])
                except Exception as e:
                    # 마이크 펄스 상태 확인 실패는 무시 (주문 처리에 영향 없음)
                    pass
                        
            except requests.exceptions.RequestException as e:
                # network error
                print(f"[NET] 네트워크 오류: {e}")
            except Exception as e:
                # parsing error or other
                print(f"[ERR] 주문 처리 오류: {e}")
                
            time.sleep(self.cfg.orders_poll_interval_sec)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.thread = threading.Thread(target=self._tick, daemon=True)
        self.thread.start()
        print("[ORDERS] 주문 수신 시작")

    def stop(self):
        self.running = False
        print("[ORDERS] 주문 수신 중지")
