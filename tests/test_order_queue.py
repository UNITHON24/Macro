import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "macro_pkg" / "macro"))

from voice.order_queue import OrderQueue  # noqa: E402


class OrderQueueTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.queue = OrderQueue(str(Path(self.directory.name) / "orders.sqlite3"))

    def tearDown(self):
        self.directory.cleanup()

    def test_fifo_claim_and_result_are_durable(self):
        first, _, _ = self.queue.enqueue([{"name": "A"}], idempotency_key="one")
        self.queue.enqueue([{"name": "B"}], idempotency_key="two")

        claimed = self.queue.claim_next()
        self.assertEqual(claimed.order_id, first)
        self.assertEqual(claimed.items[0]["name"], "A")
        self.assertEqual(self.queue.complete(first, {"success": True}), "succeeded")
        self.assertEqual(self.queue.status(first), "succeeded")
        self.assertEqual(self.queue.claim_next().order_id, "two")

    def test_idempotency_key_does_not_replace_existing_order(self):
        first = self.queue.enqueue([{"name": "A"}], idempotency_key="same")
        second = self.queue.enqueue([{"name": "A"}], idempotency_key="same")

        self.assertTrue(first[1])
        self.assertFalse(second[1])
        self.assertEqual(self.queue.claim_next().items[0]["name"], "A")

    def test_same_idempotency_key_with_different_payload_is_rejected(self):
        self.queue.enqueue([{"name": "A"}], idempotency_key="same")

        with self.assertRaises(ValueError):
            self.queue.enqueue([{"name": "B"}], idempotency_key="same")

    def test_claimed_order_is_not_blindly_replayed_after_uncertain_side_effect(self):
        self.queue.enqueue([{"name": "A"}], idempotency_key="uncertain")
        self.assertIsNotNone(self.queue.claim_next())

        self.assertIsNone(self.queue.claim_next())
        self.assertEqual(self.queue.status("uncertain"), "claimed")

    def test_uncertain_order_requires_explicit_operator_resolution(self):
        self.queue.enqueue([{"name": "A"}], idempotency_key="review")
        self.queue.claim_next()

        self.assertEqual(self.queue.resolve_uncertain("review", "failed"), "failed")
        self.assertEqual(self.queue.status("review"), "failed")
        self.assertEqual(self.queue.list_orders()[0]["order_id"], "review")

    def test_only_one_order_can_be_claimed_across_workers(self):
        self.queue.enqueue([{"name": "A"}], idempotency_key="first")
        self.queue.enqueue([{"name": "B"}], idempotency_key="second")

        self.assertEqual(self.queue.claim_next().order_id, "first")
        self.assertIsNone(OrderQueue(self.queue.path).claim_next())
        self.assertEqual(self.queue.status("second"), "queued")

    def test_side_effect_uncertainty_is_persisted_and_blocks_next_claim(self):
        self.queue.enqueue([{"name": "A"}], idempotency_key="first")
        self.queue.enqueue([{"name": "B"}], idempotency_key="second")
        self.queue.claim_next()

        self.assertEqual(
            self.queue.complete(
                "first", {"success": False, "requires_manual_review": True}
            ),
            "uncertain",
        )
        self.assertIsNone(self.queue.claim_next())

    def test_verified_live_handoff_blocks_next_claim_until_operator_resolution(self):
        self.queue.enqueue([{"name": "A"}], idempotency_key="first")
        self.queue.enqueue([{"name": "B"}], idempotency_key="second")
        self.queue.claim_next()

        self.assertEqual(
            self.queue.complete(
                "first", {"success": True, "awaiting_handoff": True}
            ),
            "awaiting_handoff",
        )
        self.assertIsNone(self.queue.claim_next())
        self.assertEqual(
            self.queue.resolve_uncertain("first", "succeeded"), "succeeded"
        )
        self.assertEqual(self.queue.claim_next().order_id, "second")


if __name__ == "__main__":
    unittest.main()
