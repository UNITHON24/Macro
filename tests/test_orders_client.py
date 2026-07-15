import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "macro_pkg" / "macro"))

from voice.orders_client import OrdersClient  # noqa: E402


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeHTTP:
    def __init__(self):
        self.posts = []

    def post(self, url, json, headers, timeout):
        self.posts.append((url, json, headers, timeout))
        return FakeResponse()


class SequentialHTTP(FakeHTTP):
    def __init__(self):
        super().__init__()
        self.order_gets = 0

    def get(self, url, headers, timeout):
        if url.endswith("/api/mic-pulse"):
            return FakeResponse(status_code=204)
        self.order_gets += 1
        return FakeResponse(
            {
                "order_id": f"order-{self.order_gets}",
                "items": [{"name": "A"}],
            }
        )


class HandoffMacro:
    def __init__(self):
        self.calls = 0

    def perform(self, items):
        self.calls += 1
        return {
            "success": True,
            "awaiting_handoff": True,
            "requires_manual_review": False,
        }


class OrdersClientTest(unittest.TestCase):
    def test_extracts_durable_delivery_envelope_and_legacy_list(self):
        self.assertEqual(
            OrdersClient._extract_delivery({"order_id": "abc", "items": [{"name": "A"}]}),
            ("abc", [{"name": "A"}]),
        )
        self.assertEqual(
            OrdersClient._extract_delivery([{"name": "A"}]),
            (None, [{"name": "A"}]),
        )

    def test_reports_macro_result_to_the_claimed_order(self):
        http = FakeHTTP()
        cfg = SimpleNamespace(
            orders_url="http://127.0.0.1:9999/api/orders",
            orders_token="test-token",
            order_result_retries=3,
        )
        client = OrdersClient(cfg, SimpleNamespace(), http=http)

        self.assertTrue(client._report_result("session/1", {"success": True}))
        self.assertEqual(
            http.posts[0][0],
            "http://127.0.0.1:9999/api/orders/session%2F1/result",
        )
        self.assertEqual(http.posts[0][2], {"X-Macro-Token": "test-token"})

    def test_live_handoff_stops_before_polling_a_second_order(self):
        http = SequentialHTTP()
        macro = HandoffMacro()
        cfg = SimpleNamespace(
            orders_url="http://127.0.0.1:9999/api/orders",
            orders_token="test-token",
            orders_poll_interval_sec=0,
            order_result_retries=1,
        )
        client = OrdersClient(cfg, macro, http=http)
        client.running = True

        client._tick()

        self.assertFalse(client.running)
        self.assertEqual(macro.calls, 1)
        self.assertEqual(http.order_gets, 1)
        self.assertEqual(len(http.posts), 1)


if __name__ == "__main__":
    unittest.main()
