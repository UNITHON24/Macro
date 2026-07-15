import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "macro_pkg" / "macro"))

from voice.errors import AutomationCancelled  # noqa: E402
from voice.macro import OrderMacro  # noqa: E402


class FakeNavigator:
    def __init__(
        self,
        outcomes=None,
        allow_payment_navigation=False,
        dry_run=True,
        payment_ready=True,
    ):
        self.idx = SimpleNamespace(
            name_to_entry={
                "아메리카노": ("커피", 1, (100, 200)),
                "레몬에이드": ("음료", 2, (300, 400)),
            }
        )
        self.cfg = SimpleNamespace(
            allow_payment_navigation=allow_payment_navigation,
            allow_checkout=allow_payment_navigation,
            dry_run=dry_run,
            max_order_items=10,
            max_item_quantity=10,
        )
        self.outcomes = outcomes or {}
        self.payment_outcome = payment_ready
        self.item_calls = []
        self.payment_calls = 0
        self.reset_count = 0
        self.last_error = None
        self.last_uncertain = False
        self.cart_mutated = False

    def add_item_like_position_test(self, name, count):
        self.item_calls.append((name, count))
        outcome = self.outcomes.get(name, True)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome and not self.cfg.dry_run:
            self.cart_mutated = True
        return outcome

    def navigate_to_payment_ready(self):
        self.payment_calls += 1
        if not self.payment_outcome:
            self.last_error = "결제 준비 화면 검증 실패"
        return self.payment_outcome

    def reset_navigation(self):
        self.reset_count += 1


class OrderMacroTest(unittest.TestCase):
    def test_empty_order_is_not_successful_and_never_navigates(self):
        navigator = FakeNavigator(allow_payment_navigation=True, dry_run=False)
        result = OrderMacro(navigator).perform([])

        self.assertFalse(result["success"])
        self.assertFalse(result["cart_success"])
        self.assertEqual(navigator.payment_calls, 0)

    def test_malformed_unknown_and_non_positive_items_fail_closed(self):
        navigator = FakeNavigator(allow_payment_navigation=True, dry_run=False)
        result = OrderMacro(navigator).perform(
            [None, {"name": "없는 메뉴", "count": 1}, {"name": "아메리카노", "count": 0}]
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["failed_items"], 3)
        self.assertEqual(navigator.item_calls, [])
        self.assertEqual(navigator.payment_calls, 0)

    def test_full_order_is_validated_before_any_item_action(self):
        navigator = FakeNavigator(allow_payment_navigation=True, dry_run=False)
        result = OrderMacro(navigator).perform(
            [{"name": "아메리카노", "count": 1}, {"name": "없는 메뉴", "count": 1}]
        )

        self.assertFalse(result["success"])
        self.assertEqual(navigator.item_calls, [])

    def test_order_and_quantity_limits_fail_before_pointer_actions(self):
        navigator = FakeNavigator(allow_payment_navigation=True, dry_run=False)
        navigator.cfg.max_order_items = 1
        too_many = OrderMacro(navigator).perform(
            [{"name": "아메리카노", "count": 1}, {"name": "레몬에이드", "count": 1}]
        )
        navigator.cfg.max_order_items = 10
        navigator.cfg.max_item_quantity = 2
        too_large = OrderMacro(navigator).perform([{"name": "아메리카노", "count": 3}])

        self.assertFalse(too_many["success"])
        self.assertFalse(too_large["success"])
        self.assertEqual(navigator.item_calls, [])

    def test_partial_navigation_failure_blocks_payment_navigation(self):
        navigator = FakeNavigator(
            outcomes={"레몬에이드": False},
            allow_payment_navigation=True,
            dry_run=False,
        )
        result = OrderMacro(navigator).perform(
            [{"name": "아메리카노", "count": 1}, {"name": "레몬에이드", "count": 1}]
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["successful_items"], 1)
        self.assertEqual(navigator.payment_calls, 0)
        self.assertTrue(result["awaiting_handoff"])

    def test_cart_success_can_stop_before_payment_when_opt_in_is_disabled(self):
        navigator = FakeNavigator(allow_payment_navigation=False)
        result = OrderMacro(navigator).perform([{"displayName": "아메리카노", "quantity": "2"}])

        self.assertTrue(result["success"])
        self.assertTrue(result["cart_success"])
        self.assertFalse(result["payment_ready"])
        self.assertIn("KIOSK_ALLOW_PAYMENT_NAVIGATION", result["payment_skip_reason"])

    def test_enabled_navigation_reaches_payment_ready_but_never_submits_payment(self):
        navigator = FakeNavigator(allow_payment_navigation=True, dry_run=False)
        result = OrderMacro(navigator).perform(
            [{"name": "아메리카노", "count": 1}, {"menuName": "레몬에이드", "qty": 2}]
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["payment_navigation_attempted"])
        self.assertTrue(result["payment_ready"])
        self.assertFalse(result["payment_clicked"])
        self.assertTrue(result["awaiting_handoff"])
        self.assertFalse(result["requires_manual_review"])
        self.assertEqual(navigator.payment_calls, 1)

    def test_unverified_payment_screen_fails_the_requested_full_flow(self):
        navigator = FakeNavigator(
            allow_payment_navigation=True,
            dry_run=False,
            payment_ready=False,
        )
        result = OrderMacro(navigator).perform([{"name": "아메리카노", "count": 1}])

        self.assertFalse(result["success"])
        self.assertTrue(result["cart_success"])
        self.assertFalse(result["payment_ready"])

    def test_uncertain_physical_result_requires_manual_review(self):
        navigator = FakeNavigator(
            outcomes={"아메리카노": False},
            allow_payment_navigation=True,
            dry_run=False,
        )
        navigator.last_uncertain = True
        # Simulate an action that occurred before its postcondition could be verified.
        original = navigator.add_item_like_position_test

        def uncertain_action(name, count):
            navigator.last_uncertain = True
            return original(name, count)

        navigator.add_item_like_position_test = uncertain_action
        result = OrderMacro(navigator).perform([{"name": "아메리카노", "count": 1}])

        self.assertTrue(result["requires_manual_review"])
        self.assertTrue(result["results"][0]["requires_manual_review"])

    def test_dry_run_reports_semantic_payment_flow_as_simulated(self):
        navigator = FakeNavigator(allow_payment_navigation=True, dry_run=True)
        result = OrderMacro(navigator).perform([{"name": "아메리카노", "count": 1}])

        self.assertTrue(result["success"])
        self.assertTrue(result["payment_simulated"])
        self.assertFalse(result["payment_clicked"])
        self.assertFalse(result["awaiting_handoff"])

    def test_verified_live_cart_still_blocks_the_next_order_until_handoff(self):
        navigator = FakeNavigator(allow_payment_navigation=False, dry_run=False)

        result = OrderMacro(navigator).perform(
            [{"displayName": "아메리카노", "quantity": 1}]
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["cart_success"])
        self.assertTrue(result["awaiting_handoff"])
        self.assertFalse(result["requires_manual_review"])

    def test_partial_quantity_mutation_also_blocks_the_next_order(self):
        navigator = FakeNavigator(dry_run=False)

        def partial_quantity(_name, _count):
            navigator.cart_mutated = True
            navigator.last_error = "두 번째 수량 추가 전 중단"
            return False

        navigator.add_item_like_position_test = partial_quantity
        result = OrderMacro(navigator).perform(
            [{"displayName": "아메리카노", "quantity": 2}]
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["successful_items"], 0)
        self.assertTrue(result["awaiting_handoff"])

    def test_operator_failsafe_stops_remaining_items_and_latches_closed(self):
        navigator = FakeNavigator(
            outcomes={"아메리카노": AutomationCancelled("emergency stop")},
            allow_payment_navigation=True,
            dry_run=False,
        )
        macro = OrderMacro(navigator)
        result = macro.perform(
            [{"name": "아메리카노", "count": 1}, {"name": "레몬에이드", "count": 1}]
        )

        self.assertTrue(result["cancelled"])
        self.assertEqual(navigator.item_calls, [("아메리카노", 1)])
        self.assertEqual(result["results"][1]["error"], "운영자가 자동화를 중단하여 실행하지 않음")
        retry = macro.perform([{"name": "레몬에이드", "count": 1}])
        self.assertTrue(retry["cancelled"])
        self.assertEqual(navigator.item_calls, [("아메리카노", 1)])

    def test_overlapping_order_is_rejected_without_actions(self):
        navigator = FakeNavigator()
        macro = OrderMacro(navigator)
        macro._execution_lock.acquire()
        try:
            result = macro.perform([{"name": "아메리카노", "count": 1}])
        finally:
            macro._execution_lock.release()

        self.assertTrue(result["busy"])
        self.assertEqual(navigator.item_calls, [])


if __name__ == "__main__":
    unittest.main()
