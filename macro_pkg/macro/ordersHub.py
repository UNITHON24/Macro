#!/usr/bin/env python3
"""Durable local HTTP handoff between the speech backend and kiosk client."""

from __future__ import annotations

import json
import hashlib
import hmac
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence
from urllib.parse import unquote, urlparse

from voice.order_queue import OrderQueue


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ordersHub")
mic_pulse_enabled = False
_queue: Optional[OrderQueue] = None


def order_token() -> str:
    return os.environ.get("KIOSK_ORDER_TOKEN", "").strip()


def validate_hub_security() -> None:
    """Every durable order queue requires an installation-specific secret."""
    if len(order_token()) < 32:
        raise RuntimeError(
            "KIOSK_ORDER_TOKEN with at least 32 characters is required"
        )


def is_authorized(headers: Mapping[str, str]) -> bool:
    expected = order_token()
    provided = str(headers.get("X-Macro-Token", "") or "").strip()
    return bool(expected and provided) and hmac.compare_digest(provided, expected)


def queue() -> OrderQueue:
    global _queue
    if _queue is None:
        default = Path.home() / ".macro" / "orders.sqlite3"
        _queue = OrderQueue(os.environ.get("KIOSK_ORDER_DB", str(default)))
    return _queue


def extract_items(payload: Any) -> Optional[Sequence[Dict[str, Any]]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get("items"), list):
            return payload["items"]
        if any(key in payload for key in ("name", "menu", "menuName", "displayName")):
            return [payload]
    return None


def idempotency_key(payload: Any, header_value: str = "") -> Optional[str]:
    if header_value.strip():
        return header_value.strip()
    if not isinstance(payload, dict):
        return None
    for key in ("idempotencyKey", "commandId", "orderId"):
        value = str(payload.get(key, "") or "").strip()
        if value:
            return value
    session_id = str(payload.get("sessionId", "") or "").strip()
    timestamp = str(payload.get("timestamp", "") or "").strip()
    if session_id and timestamp:
        canonical_items = json.dumps(
            extract_items(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical_items.encode("utf-8")).hexdigest()[:16]
        return f"{session_id}:{timestamp}:{digest}"
    return None


class OrdersHandler(BaseHTTPRequestHandler):
    max_body_bytes = 1024 * 1024

    def _send_json(self, code: int, value: Any) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _payload(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > self.max_body_bytes:
            raise ValueError("invalid content length")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _require_authorization(self) -> bool:
        if is_authorized(self.headers):
            return True
        self._send_json(401, {"success": False, "error": "unauthorized"})
        return False

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/") and not self._require_authorization():
            return
        if path == "/api/orders":
            order = queue().claim_next()
            if order is None:
                self.send_response(204)
                self.end_headers()
                return
            self._send_json(
                200,
                {
                    "order_id": order.order_id,
                    "items": list(order.items),
                    "attempt": order.attempt,
                },
            )
            return
        if path == "/api/mic-pulse":
            self._send_json(200, {"mic_pulse_enabled": mic_pulse_enabled})
            return
        if path == "/api/mic-status":
            self._send_json(200, {"status": "received"})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        global mic_pulse_enabled
        path = urlparse(self.path).path
        if path.startswith("/api/") and not self._require_authorization():
            return
        try:
            payload = self._payload()
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._send_json(400, {"success": False, "error": str(exc)})
            return

        if path == "/api/orders":
            items = extract_items(payload)
            if not items:
                self._send_json(400, {"success": False, "error": "order items are required"})
                return
            try:
                order_id, created, status = queue().enqueue(
                    items,
                    idempotency_key=idempotency_key(
                        payload, self.headers.get("Idempotency-Key", "")
                    ),
                )
            except ValueError as exc:
                self._send_json(400, {"success": False, "error": str(exc)})
                return
            self._send_json(
                200,
                {
                    "success": True,
                    "order_id": order_id,
                    "created": created,
                    "status": status,
                    "stored": len(items),
                },
            )
            return

        prefix, suffix = "/api/orders/", "/result"
        if path.startswith(prefix) and path.endswith(suffix):
            order_id = unquote(path[len(prefix) : -len(suffix)]).strip("/")
            if not order_id or not isinstance(payload, dict):
                self._send_json(400, {"success": False, "error": "invalid result"})
                return
            try:
                status = queue().complete(order_id, payload)
            except KeyError:
                self._send_json(404, {"success": False, "error": "order not found"})
                return
            except ValueError as exc:
                self._send_json(409, {"success": False, "error": str(exc)})
                return
            self._send_json(200, {"success": True, "order_id": order_id, "status": status})
            return

        if path == "/api/mic-pulse":
            if not isinstance(payload, dict) or "enable" not in payload:
                self._send_json(400, {"success": False, "error": "enable field required"})
                return
            mic_pulse_enabled = bool(payload["enable"])
            self._send_json(200, {"success": True, "mic_pulse_enabled": mic_pulse_enabled})
            return
        self.send_error(404)

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), format % args)


if __name__ == "__main__":
    try:
        validate_hub_security()
    except RuntimeError as exc:
        raise SystemExit(f"ordersHub refused to start: {exc}") from exc
    server = ThreadingHTTPServer(("127.0.0.1", 9999), OrdersHandler)
    logger.info("ordersHub started: http://127.0.0.1:9999")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("ordersHub stopped")
    finally:
        server.server_close()
