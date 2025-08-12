#!/usr/bin/env python3
"""
ordersHub.py
- 포트 9999에서 /api/orders 엔드포인트 제공
- POST /api/orders : 주문(JSON)을 저장
- GET  /api/orders : 보관된 주문을 1회 반환 후 비움(없으면 204 No Content)

run order hub:
  python ordersHub.py

매크로(run_voice.py)는 GET으로 폴링하고,
outputServer.py는 POST로 주문을 밀어넣습니다.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ordersHub")

# 메모리 내 주문 보관소(단일 큐 성격)
pending_items = None  # type: list | None

# 마이크 펄스 제어 상태
mic_pulse_enabled = False  # 백엔드에서 마이크 펄스 활성화/비활성화 제어

class OrdersHandler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        global pending_items, mic_pulse_enabled
        if self.path.startswith("/api/orders"):
            if pending_items:
                # 매크로 클라이언트가 처리하기 쉬운 형태: 리스트 그대로 반환
                items = pending_items
                pending_items = None  # 한 번 주고 비움
                logger.info(f"[HUB] GET -> deliver {items}")
                self._send_json(200, items)
            else:
                self.send_response(204)
                self.end_headers()
            return
        elif self.path.startswith("/api/mic-pulse"):
            # 마이크 펄스 상태 반환
            self._send_json(200, {"mic_pulse_enabled": mic_pulse_enabled})
            return
        elif self.path.startswith("/api/mic-status"):
            # 마이크 상태 수신 (자동 펄스에서 전송)
            self._send_json(200, {"status": "received"})
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        global pending_items, mic_pulse_enabled
        if self.path.startswith("/api/orders"):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except Exception:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception as e:
                logger.warning(f"[HUB] invalid JSON: {e}")
                self._send_json(400, {"success": False, "error": "invalid json"})
                return

            # payload에서 items 추출 시도
            items = None
            if isinstance(payload, list):
                items = payload
            elif isinstance(payload, dict):
                if isinstance(payload.get("items"), list):
                    items = payload["items"]
                elif any(k in payload for k in ("name", "menu")):
                    items = [payload]

            if not items:
                self._send_json(400, {"success": False, "error": "no items"})
                return

            pending_items = items
            logger.info(f"[HUB] POST <- store {items}")
            self._send_json(200, {"success": True, "stored": len(items)})
            return
        elif self.path.startswith("/api/mic-pulse"):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except Exception:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception as e:
                logger.warning(f"[HUB] invalid JSON: {e}")
                self._send_json(400, {"success": False, "error": "invalid json"})
                return

            # 마이크 펄스 제어 명령 처리
            if isinstance(payload, dict) and "enable" in payload:
                mic_pulse_enabled = bool(payload["enable"])
                logger.info(f"[HUB] 마이크 펄스 {'활성화' if mic_pulse_enabled else '비활성화'}")
                self._send_json(200, {
                    "success": True, 
                    "mic_pulse_enabled": mic_pulse_enabled,
                    "message": f"마이크 펄스 {'활성화' if mic_pulse_enabled else '비활성화'}됨"
                })
                return
            else:
                self._send_json(400, {"success": False, "error": "enable field required"})
                return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        logger.info("%s - %s" % (self.address_string(), format % args))

if __name__ == "__main__":
    httpd = HTTPServer(("localhost", 9999), OrdersHandler)
    logger.info("ordersHub started: http://localhost:9999")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("ordersHub stopped")
        httpd.server_close()
