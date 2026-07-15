from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Tuple

from .errors import AutomationCancelled, ProfileError

if TYPE_CHECKING:
    from .navigator import Navigator


@dataclass(frozen=True)
class _LegacyResolvedItem:
    requested_name: str
    quantity: int


class OrderMacro:
    """Prevalidate and serialize one fail-closed kiosk order at a time."""

    def __init__(self, nav: "Navigator"):
        self.nav = nav
        self.execution_history: List[Tuple[str, bool]] = []
        self._execution_lock = threading.Lock()
        self._automation_cancelled = False

    @staticmethod
    def _first(item: Mapping[str, Any], keys: Tuple[str, ...], default: Any) -> Any:
        for key in keys:
            if key in item and item[key] is not None:
                return item[key]
        return default

    @classmethod
    def _item_label(cls, item: Any, index: int) -> str:
        if isinstance(item, Mapping):
            value = cls._first(
                item, ("displayName", "menuName", "name", "menu", "item"), ""
            )
            if str(value).strip():
                return str(value).strip()
        return f"항목{index + 1}"

    @staticmethod
    def _quantity(item: Mapping[str, Any]) -> int:
        raw = OrderMacro._first(item, ("quantity", "count", "qty"), 1)
        if isinstance(raw, bool):
            raise ValueError("수량은 정수여야 함")
        count = int(raw)
        if isinstance(raw, float) and not raw.is_integer():
            raise ValueError("수량은 정수여야 함")
        return count

    def _resolve(self, item: Mapping[str, Any]) -> Any:
        profile = getattr(self.nav, "profile", None)
        if profile is not None and hasattr(profile, "resolve_order_item"):
            return profile.resolve_order_item(item)

        name = self._item_label(item, 0)
        if name not in self.nav.idx.name_to_entry:
            raise ProfileError("메뉴를 찾을 수 없음")
        return _LegacyResolvedItem(name, self._quantity(item))

    @staticmethod
    def _resolved_name(item: Any) -> str:
        menu = getattr(item, "menu", None)
        return str(getattr(menu, "name", getattr(item, "requested_name", "")))

    def _validate(self, items: Any) -> Tuple[List[Any], List[Dict[str, Any]]]:
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

        resolved_items: List[Any] = []
        failures: Dict[int, str] = {}
        display: List[Tuple[str, int]] = []
        for index, raw in enumerate(items):
            label = self._item_label(raw, index)
            count = 0
            if not isinstance(raw, Mapping):
                failures[index] = "잘못된 주문 형식"
                display.append((label, count))
                continue
            try:
                count = self._quantity(raw)
                if count < 1:
                    raise ValueError("수량은 1 이상이어야 함")
                if count > max_quantity:
                    raise ValueError(f"메뉴별 수량은 최대 {max_quantity}개까지 허용됨")
                resolved = self._resolve(raw)
                resolved_items.append(resolved)
                display.append((self._resolved_name(resolved), count))
            except (ProfileError, TypeError, ValueError) as exc:
                failures[index] = str(exc)
                display.append((label, count))

        if not failures:
            return resolved_items, []

        results: List[Dict[str, Any]] = []
        for index, (name, count) in enumerate(display):
            results.append(
                {
                    "name": name,
                    "success": False,
                    "count": count,
                    "error": failures.get(index, "다른 주문 항목 검증 실패로 실행하지 않음"),
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
        cart_success: bool = False,
        payment_navigation_attempted: bool = False,
        payment_ready: bool = False,
        payment_skip_reason: Optional[str],
        dry_run: bool = False,
        busy: bool = False,
        cancelled: bool = False,
        awaiting_handoff: bool = False,
        requires_manual_review: bool = False,
    ) -> Dict[str, Any]:
        success = cart_success and (
            not payment_navigation_attempted or payment_ready
        )
        return {
            "success": success,
            "total_items": total_items,
            "successful_items": successful_items,
            "failed_items": max(0, total_items - successful_items),
            "results": results,
            "cart_success": cart_success,
            "checkout_eligible": cart_success,
            "payment_navigation_attempted": payment_navigation_attempted,
            "payment_ready": payment_ready,
            # Compatibility fields. The module never submits an actual payment.
            "payment_clicked": False,
            "payment_simulated": payment_ready and dry_run,
            "payment_skip_reason": payment_skip_reason,
            "busy": busy,
            "cancelled": cancelled,
            "awaiting_handoff": awaiting_handoff,
            "requires_manual_review": requires_manual_review,
        }

    def perform(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_items = len(items) if isinstance(items, list) else 0
        if not self._execution_lock.acquire(blocking=False):
            return self._summary(
                total_items,
                0,
                [],
                payment_skip_reason="다른 주문이 실행 중임",
                busy=True,
            )
        try:
            if self._automation_cancelled:
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

    def _execute_item(self, item: Any) -> bool:
        if hasattr(self.nav, "add_resolved_item") and hasattr(item, "menu"):
            return bool(self.nav.add_resolved_item(item))
        return bool(self.nav.add_item_like_position_test(item.requested_name, item.quantity))

    def _perform_locked(
        self, items: List[Dict[str, Any]], total_items: int
    ) -> Dict[str, Any]:
        resolved_items, validation_results = self._validate(items)
        if validation_results:
            return self._summary(
                total_items,
                0,
                validation_results,
                payment_skip_reason="주문 검증 실패",
            )

        results: List[Dict[str, Any]] = []
        total_success = 0
        cancelled = False
        if hasattr(self.nav, "last_uncertain"):
            self.nav.last_uncertain = False
        if hasattr(self.nav, "cart_mutated"):
            self.nav.cart_mutated = False
        for index, item in enumerate(resolved_items):
            name = self._resolved_name(item)
            count = int(item.quantity)
            try:
                self.nav.reset_navigation()
                succeeded = self._execute_item(item)
                error = None if succeeded else getattr(self.nav, "last_error", None) or "매크로 실행 실패"
            except AutomationCancelled as exc:
                succeeded = False
                error = str(exc)
                cancelled = True
                self._automation_cancelled = True
            except Exception as exc:
                succeeded = False
                error = str(exc)

            manual_review = bool(
                not succeeded and getattr(self.nav, "last_uncertain", False)
            )
            results.append(
                {
                    "name": name,
                    "success": succeeded,
                    "count": count,
                    "error": error,
                    "requires_manual_review": manual_review,
                }
            )
            self.execution_history.append((name, succeeded))
            if succeeded:
                total_success += 1
                continue

            reason = (
                "운영자가 자동화를 중단하여 실행하지 않음"
                if cancelled
                else "앞선 항목 실패로 실행하지 않음"
            )
            for pending in resolved_items[index + 1 :]:
                pending_name = self._resolved_name(pending)
                results.append(
                    {
                        "name": pending_name,
                        "success": False,
                        "count": int(pending.quantity),
                        "error": reason,
                    }
                )
                self.execution_history.append((pending_name, False))
            break

        cart_success = total_success == total_items
        payment_enabled = bool(
            getattr(
                self.nav.cfg,
                "allow_payment_navigation",
                getattr(self.nav.cfg, "allow_checkout", False),
            )
        )
        attempted = cart_success and payment_enabled and not cancelled
        payment_ready = False
        if cancelled:
            reason = "운영자가 자동화를 중단함"
        elif not cart_success:
            reason = "모든 주문 항목이 성공하지 않음"
        elif not payment_enabled:
            reason = "KIOSK_ALLOW_PAYMENT_NAVIGATION이 활성화되지 않음"
        else:
            payment_ready = bool(self.nav.navigate_to_payment_ready())
            reason = None if payment_ready else getattr(self.nav, "last_error", None) or "결제 준비 화면 검증 실패"

        dry_run = bool(getattr(self.nav.cfg, "dry_run", True))
        requires_manual_review = bool(getattr(self.nav, "last_uncertain", False))
        # A verified live cart mutation is intentionally not terminal for the
        # desktop session. The customer or operator must complete/cancel the
        # handoff and restore the kiosk before another order can be claimed.
        awaiting_handoff = not dry_run and bool(
            total_success > 0 or getattr(self.nav, "cart_mutated", False)
        )

        self.nav.reset_navigation()
        return self._summary(
            total_items,
            total_success,
            results,
            cart_success=cart_success,
            payment_navigation_attempted=attempted,
            payment_ready=payment_ready,
            payment_skip_reason=reason,
            dry_run=dry_run,
            cancelled=cancelled,
            awaiting_handoff=awaiting_handoff,
            requires_manual_review=requires_manual_review,
        )

    def get_execution_history(self) -> List[Tuple[str, bool]]:
        return self.execution_history.copy()

    def clear_history(self) -> None:
        self.execution_history.clear()
