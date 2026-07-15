from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence, Tuple

from .config import Config
from .errors import AutomationCancelled, GroundingError, TransitionVerificationError
from .grounding import Target, contains_any_text, ground_target, scale_point
from .index_loader import MenuIndex
from .kiosk_profile import KioskProfile, ResolvedOrderItem
from .perception import HybridScreenObserver, ScreenObservation


@dataclass(frozen=True)
class ActionResult:
    success: bool
    verified: bool
    source: str
    before: Optional[ScreenObservation] = None
    after: Optional[ScreenObservation] = None
    error: Optional[str] = None
    acted: bool = False
    uncertain: bool = False


class Navigator:
    """Closed-loop black-box kiosk navigator.

    Live execution resolves every target from the current screen, performs one
    action, and verifies the expected postcondition before continuing.
    """

    def __init__(
        self,
        index: MenuIndex,
        cfg: Config,
        *,
        observer: Any = None,
        profile: Optional[KioskProfile] = None,
        pointer: Optional[Callable[[int, int], None]] = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.idx = index
        self.cfg = cfg
        self.profile = profile or KioskProfile.load(cfg.profile_path, index)
        self._observer = observer
        if (
            not bool(getattr(cfg, "dry_run", True))
            and observer is None
            and not str(getattr(cfg, "kiosk_window_title", "")).strip()
        ):
            raise ValueError("live mode requires KIOSK_WINDOW_TITLE to pin the target window")
        self._pointer = pointer
        self._sleep = sleeper
        self.current_category: Optional[str] = None
        self.current_page = 1
        self.last_error: Optional[str] = None
        self.last_uncertain = False
        self.cart_mutated = False

    def _screen_observer(self) -> Any:
        if self._observer is None:
            self._observer = HybridScreenObserver(self.cfg)
        return self._observer

    def observe(self) -> ScreenObservation:
        return self._screen_observer().observe()

    @staticmethod
    def _pyautogui() -> Any:
        import pyautogui  # type: ignore

        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0
        return pyautogui

    def click(self, xy: Tuple[int, int]) -> bool:
        x, y = int(xy[0]), int(xy[1])
        if self.cfg.dry_run:
            print(f"[DRY] click({x},{y})")
            return True
        try:
            if self._pointer is not None:
                self._pointer(x, y)
                return True
            pointer = self._pyautogui()
            pointer.moveTo(x, y, duration=0.1)
            pointer.click(x, y)
            return True
        except Exception as exc:
            pointer = None
            try:
                pointer = self._pyautogui()
            except Exception:
                pass
            if pointer is not None and isinstance(exc, pointer.FailSafeException):
                raise AutomationCancelled("operator activated the pointer failsafe") from exc
            self.last_error = f"pointer action failed: {exc}"
            print(f"[ERR] {self.last_error}")
            return False

    def _wait_for_postcondition(
        self,
        before: ScreenObservation,
        expected_any: Sequence[str],
        *,
        require_change: bool,
    ) -> ScreenObservation:
        deadline = time.monotonic() + float(self.cfg.transition_timeout_sec)
        last = before
        candidate: Optional[ScreenObservation] = None
        while time.monotonic() <= deadline:
            self._sleep(float(self.cfg.transition_poll_sec))
            last = self.observe()
            changed = last.signature != before.signature
            expected = not expected_any or contains_any_text(last, expected_any)
            if expected and (changed or not require_change):
                if candidate is not None and candidate.signature == last.signature:
                    return last
                candidate = last
            else:
                candidate = None
        expectation = ", ".join(expected_any) if expected_any else "screen state change"
        raise TransitionVerificationError(f"postcondition not observed: {expectation}")

    def activate(
        self,
        target: Target,
        *,
        expected_any: Sequence[str] = (),
        require_change: bool = True,
    ) -> ActionResult:
        if self.cfg.dry_run:
            labels = "/".join(target.labels)
            print(f"[DRY] semantic action {target.key}: {labels}")
            if target.fallback_xy is not None:
                self.click(target.fallback_xy)
            return ActionResult(True, True, "dry-run")

        try:
            before = self.observe()
            grounded = None
            acted = False
            try:
                grounded = ground_target(
                    before,
                    target,
                    cutoff=float(self.cfg.match_cutoff),
                    ambiguity_margin=float(self.cfg.ambiguity_margin),
                )
            except GroundingError:
                observe_with_ocr = getattr(self._screen_observer(), "observe_with_ocr", None)
                if callable(observe_with_ocr):
                    before = observe_with_ocr()
                    try:
                        grounded = ground_target(
                            before,
                            target,
                            cutoff=float(self.cfg.match_cutoff),
                            ambiguity_margin=float(self.cfg.ambiguity_margin),
                        )
                    except GroundingError:
                        grounded = None
                if grounded is None and (
                    not self.cfg.allow_coordinate_fallback or target.fallback_xy is None
                ):
                    raise

            source = "coordinate"
            if grounded is not None:
                source = grounded.element.source
                invoked = bool(
                    grounded.element.source == "uia"
                    and self._screen_observer().invoke(grounded.element)
                )
                if not invoked and not self.click(grounded.element.rect.center):
                    raise RuntimeError("resolved target could not be activated")
                acted = True
            else:
                point = scale_point(
                    target.fallback_xy,
                    self.profile.reference_size,
                    (before.width, before.height),
                )
                point = (
                    point[0] + int(getattr(before, "origin_x", 0)),
                    point[1] + int(getattr(before, "origin_y", 0)),
                )
                if not self.click(point):
                    raise RuntimeError("coordinate fallback failed")
                acted = True

            after = self._wait_for_postcondition(
                before,
                expected_any,
                require_change=require_change,
            )
            self.last_error = None
            return ActionResult(True, True, source, before, after, acted=True)
        except AutomationCancelled:
            raise
        except Exception as exc:
            self.last_error = str(exc)
            acted = bool(locals().get("acted", False))
            if acted:
                self.last_uncertain = True
            print(f"[ERR] {target.key}: {exc}")
            return ActionResult(
                False,
                False,
                locals().get("source", "none"),
                locals().get("before"),
                error=str(exc),
                acted=acted,
                uncertain=acted,
            )

    def _page_markers(self, category: str, page: int) -> Tuple[str, ...]:
        return tuple(
            name
            for name, (menu_category, menu_page, _) in self.idx.name_to_entry.items()
            if menu_category == category and menu_page == page
        )

    def _region_texts(
        self,
        observation: ScreenObservation,
        region: Optional[Tuple[float, float, float, float]],
    ) -> Tuple[str, ...]:
        if region is None:
            return tuple("".join(text.split()).casefold() for text in observation.texts)
        left, top, right, bottom = region
        width, height = max(1, observation.width), max(1, observation.height)
        origin_x = int(getattr(observation, "origin_x", 0))
        origin_y = int(getattr(observation, "origin_y", 0))
        values = []
        for element in observation.elements:
            x, y = element.rect.center
            normalized_x = (x - origin_x) / width
            normalized_y = (y - origin_y) / height
            if left <= normalized_x <= right and top <= normalized_y <= bottom:
                value = "".join(element.text.split()).casefold()
                if value:
                    values.append(value)
        return tuple(values)

    def _page_evidence(
        self, observation: ScreenObservation, category: str, page: int
    ) -> bool:
        markers = tuple("".join(value.split()).casefold() for value in self._page_markers(category, page))
        if not markers:
            return False
        visible = self._region_texts(observation, self.profile.menu_region)
        matched = sum(
            any(marker == text or marker in text for text in visible) for marker in markers
        )
        return matched >= min(2, len(markers))

    def go_category(self, category: str) -> bool:
        fallback = self.idx.category_centers.get(category)
        if fallback is None:
            self.last_error = f"category is not calibrated: {category}"
            return False
        target = self.profile.target(
            f"category:{category}",
            category,
            fallback_xy=fallback,
        )
        if not self.cfg.dry_run:
            try:
                current = self.observe()
                if self._page_evidence(current, category, 1):
                    self.current_category = category
                    self.current_page = 1
                    return True
            except Exception as exc:
                self.last_error = str(exc)
                return False
        result = self.activate(
            target,
            expected_any=self._page_markers(category, 1),
            require_change=not self.cfg.dry_run,
        )
        if result.success and (
            self.cfg.dry_run
            or (result.after is not None and self._page_evidence(result.after, category, 1))
        ):
            self.current_category = category
            self.current_page = 1
            return True
        self.last_error = self.last_error or f"category page was not verified: {category}"
        return False

    def go_page_from_one(self, category: str, target_page: int) -> bool:
        if target_page <= 1:
            self.current_page = 1
            return True
        for page in range(2, target_page + 1):
            target = self.profile.target(
                "next",
                "다음",
                fallback_xy=self.idx.next_xy,
            )
            result = self.activate(
                target,
                expected_any=self._page_markers(category, page),
                require_change=not self.cfg.dry_run,
            )
            if not result.success or (
                not self.cfg.dry_run
                and (result.after is None or not self._page_evidence(result.after, category, page))
            ):
                self.last_error = self.last_error or f"page was not verified: {page}"
                return False
            self.current_page = page
        return True

    def _visible(self, observation: ScreenObservation, target: Target) -> bool:
        try:
            ground_target(
                observation,
                target,
                cutoff=float(self.cfg.match_cutoff),
                ambiguity_margin=float(self.cfg.ambiguity_margin),
            )
            return True
        except GroundingError:
            return False

    def _cart_semantic_signature(self, observation: ScreenObservation) -> Tuple[str, ...]:
        if self.profile.cart_region is None:
            return ()
        return tuple(sorted(self._region_texts(observation, self.profile.cart_region)))

    def _item_addition_verified(
        self,
        before: ScreenObservation,
        after: ScreenObservation,
        menu_name: str,
    ) -> bool:
        before_cart = self._cart_semantic_signature(before)
        after_cart = self._cart_semantic_signature(after)
        if before_cart and after_cart and before_cart != after_cart:
            return True

        before_texts = tuple("".join(text.split()).casefold() for text in before.texts)
        after_texts = tuple("".join(text.split()).casefold() for text in after.texts)
        for template in self.profile.item_added_markers:
            marker = "".join(template.format(menu=menu_name).split()).casefold()
            if marker and not any(marker in text for text in before_texts) and any(
                marker in text for text in after_texts
            ):
                return True
        return False

    def _add_one(self, item: ResolvedOrderItem) -> bool:
        menu = item.menu
        menu_target = Target(
            key=f"menu:{menu.name}",
            labels=(
                f"{menu.name} 장바구니에 추가",
                f"{item.requested_name} 장바구니에 추가",
                menu.name,
                item.requested_name,
            ),
            roles=("ButtonControl", "ListItemControl", "button", "text"),
            fallback_xy=menu.fallback_xy,
            region=self.profile.menu_region,
        )

        if not self.cfg.dry_run:
            try:
                already_visible = self._visible(self.observe(), menu_target)
            except Exception:
                already_visible = False
        else:
            already_visible = False

        if not already_visible:
            if not self.go_category(menu.category):
                return False
            if not self.go_page_from_one(menu.category, menu.page):
                return False

        result = self.activate(menu_target, require_change=True)
        if not result.success:
            return False
        before_item_action = result.before

        for option in item.option_targets:
            option_result = self.activate(option, require_change=True)
            if not option_result.success:
                self.last_uncertain = True
                return False

        if self.cfg.dry_run:
            return True

        current = self.observe()
        confirm = Target(
            key="confirm-item",
            labels=self.profile.confirm_labels,
            roles=("ButtonControl", "button"),
        )
        if confirm.labels and self._visible(current, confirm):
            confirmed = self.activate(
                confirm,
                expected_any=self.profile.cart_added_markers,
                require_change=True,
            )
            if not confirmed.success:
                self.last_uncertain = True
                return False
            current = confirmed.after or self.observe()

        state = self.profile.transition_graph().detect_state(current)
        if state not in {"menu", "cart"}:
            self.last_error = "item action did not return to a verified menu/cart state"
            print(f"[ERR] {self.last_error}")
            self.last_uncertain = True
            return False
        if before_item_action is None or not self._item_addition_verified(
            before_item_action, current, menu.name
        ):
            self.last_error = "cart contents did not provide evidence that the item was added"
            print(f"[ERR] {self.last_error}")
            self.last_uncertain = True
            return False
        self.cart_mutated = True
        return True

    def add_resolved_item(self, item: ResolvedOrderItem) -> bool:
        for _ in range(item.quantity):
            if not self._add_one(item):
                return False
        return True

    def add_item(self, name: str, count: int = 1) -> bool:
        try:
            item = self.profile.resolve_order_item({"name": name, "quantity": count})
        except Exception as exc:
            self.last_error = str(exc)
            return False
        return self.add_resolved_item(item)

    def add_item_direct(self, name: str, count: int = 1) -> bool:
        return self.add_item(name, count)

    def add_item_like_position_test(self, name: str, count: int = 1) -> bool:
        return self.add_item(name, count)

    def navigate_to_payment_ready(self) -> bool:
        if not bool(getattr(self.cfg, "allow_payment_navigation", False)):
            self.last_error = "KIOSK_ALLOW_PAYMENT_NAVIGATION is disabled"
            return False
        graph = self.profile.transition_graph()
        if self.cfg.dry_run:
            state = "menu"
        else:
            observation = self.observe()
            state = graph.detect_state(observation)
            if state == "payment_ready":
                return True
            if state is None:
                checkout = self.profile.target(
                    "checkout",
                    "결제하기",
                    "주문하기",
                    fallback_xy=(self.cfg.checkout_x, self.cfg.checkout_y),
                )
                if not self._visible(observation, checkout):
                    self.last_error = "current kiosk state is unknown"
                    return False
                state = "menu"
        try:
            path = graph.path(state, "payment_ready")
        except ValueError as exc:
            self.last_error = str(exc)
            return False

        for transition in path:
            target = transition.target
            if target.key == "checkout":
                target = Target(
                    key=target.key,
                    labels=target.labels,
                    roles=target.roles,
                    fallback_xy=(self.cfg.checkout_x, self.cfg.checkout_y),
                )
            result = self.activate(
                target,
                expected_any=transition.expected_any,
                require_change=True,
            )
            if not result.success:
                return False

        if self.cfg.dry_run:
            return True
        final = self.observe()
        if graph.detect_state(final) != "payment_ready":
            self.last_error = "payment-ready screen was not verified"
            self.last_uncertain = True
            return False
        print("[PAY] 결제 준비 화면을 확인했습니다. 실제 결제 입력 없이 정지합니다.")
        return True

    def reset_navigation(self) -> None:
        self.current_category = None
        self.current_page = 1
