import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "macro_pkg" / "macro"))

from voice.macro import OrderMacro  # noqa: E402
from voice.errors import AutomationCancelled  # noqa: E402


class FakeNavigator:
    def __init__(self, outcomes=None, allow_checkout=False, dry_run=True):
        self.idx = SimpleNamespace(
            name_to_entry={
                "아메리카노": ("커피", 1, (100, 200)),
                "레몬에이드": ("음료", 2, (300, 400)),
            }
        )
        self.cfg = SimpleNamespace(
            allow_checkout=allow_checkout,
            dry_run=dry_run,
            checkout_x=989,
            checkout_y=1880,
            item_click_delay=0,
            max_order_items=10,
            max_item_quantity=10,
        )
        self.outcomes = outcomes or {}
        self.clicks = []
        self.item_calls = []
        self.reset_count = 0

    def add_item_like_position_test(self, name, count):
        self.item_calls.append((name, count))
        outcome = self.outcomes.get(name, True)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def click(self, coordinates):
        self.clicks.append(coordinates)
        return True

    def reset_navigation(self):
        self.reset_count += 1


class OrderMacroTest(unittest.TestCase):
    def test_empty_order_is_not_successful_and_never_checks_out(self):
        navigator = FakeNavigator(allow_checkout=True, dry_run=False)
        result = OrderMacro(navigator).perform([])

        self.assertFalse(result["success"])
        self.assertFalse(result["checkout_eligible"])
        self.assertFalse(result["payment_clicked"])
        self.assertEqual(navigator.clicks, [])

    def test_malformed_unknown_and_non_positive_items_fail_closed(self):
        navigator = FakeNavigator(allow_checkout=True, dry_run=False)
        result = OrderMacro(navigator).perform(
            [None, {"name": "없는 메뉴", "count": 1}, {"name": "아메리카노", "count": 0}]
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["failed_items"], 3)
        self.assertFalse(result["payment_clicked"])
        self.assertEqual(navigator.clicks, [])
        self.assertEqual(navigator.item_calls, [])

    def test_full_order_is_validated_before_any_item_action(self):
        navigator = FakeNavigator(allow_checkout=True, dry_run=False)
        result = OrderMacro(navigator).perform(
            [{"name": "아메리카노", "count": 1}, {"name": "없는 메뉴", "count": 1}]
        )

        self.assertFalse(result["success"])
        self.assertEqual(navigator.item_calls, [])

    def test_order_and_quantity_limits_fail_before_pointer_actions(self):
        navigator = FakeNavigator(allow_checkout=True, dry_run=False)
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

    def test_partial_navigation_failure_blocks_checkout(self):
        navigator = FakeNavigator(
            outcomes={"레몬에이드": False}, allow_checkout=True, dry_run=False
        )
        macro = OrderMacro(navigator)
        result = macro.perform(
            [{"name": "아메리카노", "count": 1}, {"name": "레몬에이드", "count": 1}]
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["successful_items"], 1)
        self.assertFalse(result["payment_clicked"])
        self.assertFalse(result["payment_simulated"])
        self.assertEqual(navigator.clicks, [])

    def test_successful_items_still_require_checkout_opt_in(self):
        navigator = FakeNavigator(allow_checkout=False)
        result = OrderMacro(navigator).perform([{"displayName": "아메리카노", "quantity": "2"}])

        self.assertTrue(result["success"])
        self.assertTrue(result["checkout_eligible"])
        self.assertFalse(result["payment_clicked"])
        self.assertIn("KIOSK_ALLOW_CHECKOUT", result["payment_skip_reason"])
        self.assertEqual(navigator.clicks, [])

    def test_live_mode_never_clicks_checkout_even_after_full_success(self):
        navigator = FakeNavigator(allow_checkout=True, dry_run=False)
        result = OrderMacro(navigator).perform(
            [{"name": "아메리카노", "count": 1}, {"menuName": "레몬에이드", "qty": 2}]
        )

        self.assertTrue(result["success"])
        self.assertFalse(result["payment_clicked"])
        self.assertFalse(result["payment_simulated"])
        self.assertIn("수동", result["payment_skip_reason"])
        self.assertEqual(navigator.clicks, [])

    def test_dry_run_reports_checkout_as_simulated_not_clicked(self):
        navigator = FakeNavigator(allow_checkout=True, dry_run=True)
        result = OrderMacro(navigator).perform([{"name": "아메리카노", "count": 1}])

        self.assertTrue(result["success"])
        self.assertFalse(result["payment_clicked"])
        self.assertTrue(result["payment_simulated"])
        self.assertEqual(navigator.clicks, [(989, 1880)])

    def test_operator_failsafe_stops_remaining_items(self):
        navigator = FakeNavigator(
            outcomes={"아메리카노": AutomationCancelled("emergency stop")},
            allow_checkout=True,
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
        self.assertIn("재시작", retry["payment_skip_reason"])
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
