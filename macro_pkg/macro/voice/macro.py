from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from .errors import AutomationCancelled

if TYPE_CHECKING:
    from .navigator import Navigator


class OrderMacro:
    """Validate and serialize one fail-closed kiosk order at a time."""

    def __init__(self, nav: "Navigator"):
        self.nav = nav
        self.execution_history: List[Tuple[str, bool]] = []
        self._execution_lock = threading.Lock()
        self._automation_cancelled = False

    @staticmethod
    def _first(item: Dict[str, Any], keys: Tuple[str, ...], default: Any) -> Any:
        for key in keys:
            if key in item and item[key] is not None:
                return item[key]
        return default

    @staticmethod
    def _item_label(item: Any, index: int) -> str:
        if isinstance(item, dict):
            raw_name = OrderMacro._first(
                item, ("name", "menu", "item", "displayName", "menuName"), ""
            )
            if str(raw_name).strip():
                return str(raw_name).strip()
        return f"항목{index + 1}"

    def _validate(self, items: Any) -> Tuple[List[Tuple[str, int]], List[Dict[str, Any]]]:
        if not isinstance(items, list) or not items:
            return [], [
                {"name": "주문", "success": False, "count": 0, "error": "주문 항목이 없음"}
            ]

        max_items = max(1, int(getattr(self.nav.cfg, "max_order_items", 10)))
        max_quantity = max(1, int(getattr(self.nav.cfg, "max_item_quantity", 10)))
        if len(items) > max_items:
            return [], [
                {
                    "name": "주문",
                    "success": False,
                    "count": len(items),
                    "error": f"주문 항목은 최대 {max_items}개까지 허용됨",
                }
            ]

        normalized: List[Tuple[str, int]] = []
        validation_errors: Dict[int, str] = {}

        for index, item in enumerate(items):
            if not isinstance(item, dict):
                validation_errors[index] = "잘못된 주문 형식"
                normalized.append((self._item_label(item, index), 0))
                continue

            raw_name = self._first(
                item, ("name", "menu", "item", "displayName", "menuName"), ""
            )
            name = str(raw_name).strip()
            raw_count = self._first(item, ("count", "qty", "quantity"), 1)

            try:
                if isinstance(raw_count, bool):
                    raise ValueError
                count = int(raw_count)
                if isinstance(raw_count, float) and not raw_count.is_integer():
                    raise ValueError
            except (TypeError, ValueError):
                count = 0

            normalized.append((name or self._item_label(item, index), count))

            if not name:
                validation_errors[index] = "메뉴명 없음"
            elif count < 1:
                validation_errors[index] = "수량은 1 이상이어야 함"
            elif count > max_quantity:
                validation_errors[index] = f"메뉴별 수량은 최대 {max_quantity}개까지 허용됨"
            elif name not in self.nav.idx.name_to_entry:
                validation_errors[index] = "메뉴를 찾을 수 없음"

        if not validation_errors:
            return normalized, []

        results: List[Dict[str, Any]] = []
        for index, (name, count) in enumerate(normalized):
            results.append(
                {
                    "name": name,
                    "success": False,
                    "count": count,
                    "error": validation_errors.get(
                        index, "다른 주문 항목 검증 실패로 실행하지 않음"
                    ),
                }
            )
            self.execution_history.append((name, False))
        return [], results

    @staticmethod
    def _summary(
        total_items: int,
        successful_items: int,
        results: List[Dict[str, Any]],
        *,
        checkout_eligible: bool = False,
        payment_simulated: bool = False,
        payment_skip_reason: Optional[str],
        busy: bool = False,
        cancelled: bool = False,
    ) -> Dict[str, Any]:
        return {
            "success": checkout_eligible,
            "total_items": total_items,
            "successful_items": successful_items,
            "failed_items": max(0, total_items - successful_items),
            "results": results,
            "checkout_eligible": checkout_eligible,
            "payment_clicked": False,
            "payment_simulated": payment_simulated,
            "payment_skip_reason": payment_skip_reason,
            "busy": busy,
            "cancelled": cancelled,
        }

    def perform(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate the full order before any click and execute it without overlap."""
        total_items = len(items) if isinstance(items, list) else 0
        if not self._execution_lock.acquire(blocking=False):
            print("[MACRO] 다른 주문이 실행 중이어서 새 주문을 거부합니다.")
            return self._summary(
                total_items,
                0,
                [],
                payment_skip_reason="다른 주문이 실행 중임",
                busy=True,
            )

        try:
            if self._automation_cancelled:
                print("[MACRO] 긴급 중단 이후에는 클라이언트를 재시작해야 합니다.")
                return self._summary(
                    total_items,
                    0,
                    [],
                    payment_skip_reason="긴급 중단 후 재시작이 필요함",
                    cancelled=True,
                )
            return self._perform_locked(items, total_items)
        finally:
            self._execution_lock.release()

    def _perform_locked(
        self, items: List[Dict[str, Any]], total_items: int
    ) -> Dict[str, Any]:
        print(f"[MACRO] 주문 처리 시작: {total_items}개 항목")
        normalized, validation_results = self._validate(items)
        if validation_results:
            print("[MACRO] 주문 전체 검증에 실패하여 포인터 동작을 실행하지 않습니다.")
            return self._summary(
                total_items,
                0,
                validation_results,
                payment_skip_reason="주문 검증 실패",
            )

        results: List[Dict[str, Any]] = []
        total_success = 0
        cancelled = False

        for index, (name, count) in enumerate(normalized):
            print(f"[MACRO] 항목 {index + 1}: '{name}' {count}개 처리 중...")
            try:
                self.nav.reset_navigation()
                success = self.nav.add_item_like_position_test(name, count)
                error = None if success else "매크로 실행 실패"
            except AutomationCancelled as exc:
                success = False
                error = str(exc)
                cancelled = True
                self._automation_cancelled = True
            except Exception as exc:
                success = False
                error = str(exc)

            results.append({"name": name, "success": success, "count": count, "error": error})
            self.execution_history.append((name, success))

            if success:
                total_success += 1
                continue

            reason = "운영자가 자동화를 중단하여 실행하지 않음" if cancelled else "앞선 항목 실패로 실행하지 않음"
            for pending_name, pending_count in normalized[index + 1 :]:
                results.append(
                    {
                        "name": pending_name,
                        "success": False,
                        "count": pending_count,
                        "error": reason,
                    }
                )
                self.execution_history.append((pending_name, False))
            break

        all_succeeded = total_success == total_items
        checkout_enabled = bool(getattr(self.nav.cfg, "allow_checkout", False))
        dry_run = bool(getattr(self.nav.cfg, "dry_run", True))
        payment_simulated = False

        if cancelled:
            payment_skip_reason = "운영자가 자동화를 중단함"
        elif not all_succeeded:
            payment_skip_reason = "모든 주문 항목이 성공하지 않음"
        elif not checkout_enabled:
            payment_skip_reason = "KIOSK_ALLOW_CHECKOUT이 활성화되지 않음"
        elif not dry_run:
            payment_skip_reason = "실제 결제는 화면 상태를 확인한 운영자가 수동으로 완료해야 함"
        else:
            checkout_xy = (
                int(getattr(self.nav.cfg, "checkout_x", 989)),
                int(getattr(self.nav.cfg, "checkout_y", 1880)),
            )
            print(f"[PAY][DRY] 결제하기 동작 시뮬레이션 @ {checkout_xy}")
            payment_simulated = self.nav.click(checkout_xy) is not False
            payment_skip_reason = None if payment_simulated else "결제하기 시뮬레이션 실패"
            if payment_simulated:
                time.sleep(self.nav.cfg.item_click_delay)

        if payment_skip_reason:
            print(f"[PAY] 결제하기 건너뜀: {payment_skip_reason}")

        self.nav.reset_navigation()
        print(f"[MACRO] 주문 처리 완료: {total_success}/{total_items} 성공")
        return self._summary(
            total_items,
            total_success,
            results,
            checkout_eligible=all_succeeded,
            payment_simulated=payment_simulated,
            payment_skip_reason=payment_skip_reason,
            cancelled=cancelled,
        )

    def get_execution_history(self) -> List[Tuple[str, bool]]:
        return self.execution_history.copy()

    def clear_history(self) -> None:
        self.execution_history.clear()
