from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import quote

from .config import Config
from .macro import OrderMacro


class OrdersClient:
    """Claim durable orders, execute once, and acknowledge the observed result."""

    def __init__(
        self,
        cfg: Config,
        macro: OrderMacro,
        on_server_stop: Optional[Callable[[], None]] = None,
        http: Any = None,
    ):
        self.cfg = cfg
        self.macro = macro
        self.on_server_stop = on_server_stop
        self._http_client = http
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self.overlay = None

    def _http(self) -> Any:
        if self._http_client is None:
            import requests  # type: ignore

            self._http_client = requests
        return self._http_client

    def _headers(self) -> Dict[str, str]:
        token = str(getattr(self.cfg, "orders_token", "") or "").strip()
        return {"X-Macro-Token": token} if token else {}

    def set_overlay(self, overlay: Any) -> None:
        self.overlay = overlay

    @staticmethod
    def _extract_delivery(payload: Any) -> Tuple[Optional[str], Optional[list]]:
        if isinstance(payload, list):
            return None, payload
        if isinstance(payload, dict):
            order_id = str(payload.get("order_id", "") or "").strip() or None
            if isinstance(payload.get("items"), list):
                return order_id, payload["items"]
            if payload.get("type") == "final" and isinstance(payload.get("items"), list):
                return order_id, payload["items"]
            if any(key in payload for key in ("name", "menu", "menuName", "displayName")):
                return order_id, [payload]
        return None, None

    def _extract_items(self, payload: Any) -> Optional[list]:
        return self._extract_delivery(payload)[1]

    def _report_result(self, order_id: str, result: Dict[str, Any]) -> bool:
        url = f"{self.cfg.orders_url.rstrip('/')}/{quote(order_id, safe='')}/result"
        retries = max(1, int(getattr(self.cfg, "order_result_retries", 3)))
        for attempt in range(retries):
            try:
                response = self._http().post(
                    url, json=result, headers=self._headers(), timeout=2
                )
                response.raise_for_status()
                return True
            except Exception as exc:
                print(f"[NET] 주문 결과 보고 실패 ({attempt + 1}/{retries}): {exc}")
                if attempt + 1 < retries:
                    time.sleep(min(1.0, 0.2 * (2**attempt)))
        return False

    def _set_processing(self, processing: bool) -> None:
        if self.overlay:
            self.overlay.set_processing_order(processing)

    def _poll_mic_pulse(self) -> None:
        if not self.overlay:
            return
        url = self.cfg.orders_url.replace("/api/orders", "/api/mic-pulse")
        try:
            response = self._http().get(url, headers=self._headers(), timeout=1)
            if response.status_code == 200:
                payload = response.json()
                if "mic_pulse_enabled" in payload:
                    self.overlay.enable_mic_pulse(payload["mic_pulse_enabled"])
        except Exception:
            pass

    def _tick(self) -> None:
        while self.running:
            try:
                response = self._http().get(
                    self.cfg.orders_url, headers=self._headers(), timeout=2
                )
                if response.status_code == 204:
                    self._poll_mic_pulse()
                    time.sleep(self.cfg.orders_poll_interval_sec)
                    continue
                response.raise_for_status()
                payload = response.json()
                order_id, items = self._extract_delivery(payload)
                if items:
                    self._set_processing(True)
                    try:
                        result = self.macro.perform(items)
                    except Exception as exc:
                        result = {
                            "success": False,
                            "error": str(exc),
                            "requires_manual_review": True,
                        }
                    finally:
                        self._set_processing(False)
                    if order_id and not self._report_result(order_id, result):
                        print(
                            "[STOP] 결과 ACK를 확인할 수 없어 중복 실행 방지를 위해 "
                            "주문 수신을 중단합니다."
                        )
                        self.running = False
                    elif result.get("requires_manual_review"):
                        print(
                            "[STOP] 키오스크 반영 여부가 불확실해 운영자 확인 전까지 "
                            "주문 수신을 중단합니다."
                        )
                        self.running = False
                    elif result.get("awaiting_handoff"):
                        print(
                            "[STOP] 고객 인계와 키오스크 초기화를 확인하기 전까지 "
                            "주문 수신을 중단합니다."
                        )
                        self.running = False
                elif (
                    isinstance(payload, dict)
                    and payload.get("type") == "stop"
                    and self.on_server_stop
                ):
                    self.on_server_stop()
                self._poll_mic_pulse()
            except Exception as exc:
                print(f"[NET] 주문 수신 오류: {exc}")
            time.sleep(self.cfg.orders_poll_interval_sec)

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.thread = threading.Thread(target=self._tick, daemon=True)
        self.thread.start()
        print("[ORDERS] 주문 수신 시작")

    def stop(self) -> None:
        self.running = False
        print("[ORDERS] 주문 수신 중지")
