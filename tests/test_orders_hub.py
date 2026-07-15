import sys
import os
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "macro_pkg" / "macro"))

from ordersHub import idempotency_key, is_authorized, validate_hub_security  # noqa: E402


class OrdersHubTest(unittest.TestCase):
    def test_session_timestamp_and_payload_form_retry_key(self):
        first = {
            "sessionId": "session",
            "timestamp": "2026-07-15T12:00:00Z",
            "items": [{"menuName": "americano", "quantity": 1}],
        }
        retry = dict(first)
        next_order = {
            **first,
            "timestamp": "2026-07-15T12:01:00Z",
        }

        self.assertEqual(idempotency_key(first), idempotency_key(retry))
        self.assertNotEqual(idempotency_key(first), idempotency_key(next_order))

    def test_session_without_timestamp_is_not_treated_as_a_permanent_order_id(self):
        self.assertIsNone(
            idempotency_key({"sessionId": "session", "items": [{"name": "A"}]})
        )

    def test_live_hub_requires_a_long_installation_token(self):
        with patch.dict(
            os.environ,
            {"KIOSK_DRY_RUN": "0", "KIOSK_ORDER_TOKEN": "short"},
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                validate_hub_security()

    def test_dry_run_is_not_a_tokenless_durable_queue_bypass(self):
        with patch.dict(
            os.environ,
            {"KIOSK_DRY_RUN": "1", "KIOSK_ORDER_TOKEN": ""},
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                validate_hub_security()
            self.assertFalse(is_authorized({}))

    def test_configured_token_uses_exact_header_authentication(self):
        token = "a" * 32
        with patch.dict(
            os.environ,
            {"KIOSK_DRY_RUN": "0", "KIOSK_ORDER_TOKEN": token},
            clear=False,
        ):
            self.assertTrue(is_authorized({"X-Macro-Token": token}))
            self.assertFalse(is_authorized({"X-Macro-Token": token[:-1] + "b"}))
            self.assertFalse(is_authorized({}))


if __name__ == "__main__":
    unittest.main()
