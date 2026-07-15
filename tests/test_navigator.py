import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "macro_pkg" / "macro"))

from voice.grounding import Target  # noqa: E402
from voice.kiosk_profile import KioskProfile, MenuRecord, ResolvedOrderItem  # noqa: E402
from voice.navigator import Navigator  # noqa: E402
from voice.perception import ObservedElement, Rect, ScreenObservation  # noqa: E402


def screen(texts, *, source="ocr", visual_hash="state"):
    elements = tuple(
        ObservedElement(text, Rect(10 + index * 120, 10, 110 + index * 120, 60), source=source, role="ButtonControl")
        for index, text in enumerate(texts)
    )
    return ScreenObservation(elements, 200, 300, visual_hash=visual_hash)


class ReplayObserver:
    def __init__(self, observations, invoke=True):
        self.observations = list(observations)
        self.index = 0
        self.invoke_result = invoke
        self.invoked = []

    def observe(self):
        value = self.observations[min(self.index, len(self.observations) - 1)]
        self.index += 1
        return value

    def invoke(self, element):
        self.invoked.append(element.text)
        return self.invoke_result


def profile():
    return KioskProfile(
        {
            "schema_version": 2,
            "reference_viewport": {"width": 100, "height": 100},
            "aliases": {},
            "modifiers": {},
            "states": {
                "menu": ["커피"],
                "payment_ready": ["결제 방법 선택", "카드 결제"],
            },
            "state_priority": ["payment_ready", "menu"],
            "transitions": [
                {
                    "source": "menu",
                    "destination": "payment_ready",
                    "target": {"key": "checkout", "labels": ["결제하기"]},
                    "expected_any": ["결제 방법 선택"],
                },
            ],
            "cart_added_markers": ["장바구니"],
            "item_added_markers": ["{menu} 추가 완료"],
            "menu_region": [0.0, 0.0, 0.5, 1.0],
            "cart_region": [0.5, 0.0, 1.0, 1.0],
            "confirm_labels": ["담기"],
        },
        [],
    )


def config(**overrides):
    values = dict(
        dry_run=False,
        allow_payment_navigation=True,
        allow_coordinate_fallback=False,
        match_cutoff=0.82,
        ambiguity_margin=0.08,
        transition_timeout_sec=0.002,
        transition_poll_sec=0.0001,
        checkout_x=50,
        checkout_y=90,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class NavigatorTest(unittest.TestCase):
    def test_action_succeeds_only_after_observed_postcondition(self):
        before = screen(["담기"], visual_hash="before")
        after = screen(["장바구니"], visual_hash="after")
        pointer = []
        nav = Navigator(
            SimpleNamespace(category_centers={}, name_to_entry={}),
            config(),
            observer=ReplayObserver([before, after, after], invoke=False),
            profile=profile(),
            pointer=lambda x, y: pointer.append((x, y)),
            sleeper=lambda _: None,
        )

        result = nav.activate(Target("add", ("담기",)), expected_any=("장바구니",))

        self.assertTrue(result.success)
        self.assertTrue(result.verified)
        self.assertEqual(pointer, [(60, 35)])

    def test_unchanged_screen_fails_closed_even_when_click_api_succeeds(self):
        unchanged = screen(["담기"], visual_hash="same")
        nav = Navigator(
            SimpleNamespace(category_centers={}, name_to_entry={}),
            config(),
            observer=ReplayObserver([unchanged]),
            profile=profile(),
            pointer=lambda _x, _y: None,
            sleeper=lambda _: None,
        )

        result = nav.activate(Target("add", ("담기",)))

        self.assertFalse(result.success)
        self.assertIn("postcondition", result.error)
        self.assertTrue(result.uncertain)
        self.assertTrue(nav.last_uncertain)

    def test_coordinate_fallback_is_scaled_and_requires_explicit_opt_in(self):
        before = screen(["다른 텍스트"], visual_hash="before")
        after = screen(["완료"], visual_hash="after")
        pointer = []
        nav = Navigator(
            SimpleNamespace(category_centers={}, name_to_entry={}),
            config(allow_coordinate_fallback=True),
            observer=ReplayObserver([before, after, after]),
            profile=profile(),
            pointer=lambda x, y: pointer.append((x, y)),
            sleeper=lambda _: None,
        )

        result = nav.activate(Target("missing", ("없음",), fallback_xy=(50, 50)))

        self.assertTrue(result.success)
        self.assertEqual(pointer, [(100, 150)])

    def test_payment_flow_invokes_semantic_controls_and_stops_at_ready_screen(self):
        menu = screen(["커피", "결제하기"], source="uia", visual_hash="menu")
        ready = screen(["결제 방법 선택", "카드 결제"], source="uia", visual_hash="ready")
        replay = ReplayObserver(
            [menu, menu, ready, ready, ready],
            invoke=True,
        )
        pointer = []
        nav = Navigator(
            SimpleNamespace(category_centers={}, name_to_entry={}),
            config(),
            observer=replay,
            profile=profile(),
            pointer=lambda x, y: pointer.append((x, y)),
            sleeper=lambda _: None,
        )

        self.assertTrue(nav.navigate_to_payment_ready())
        self.assertEqual(replay.invoked, ["결제하기"])
        self.assertEqual(pointer, [])

    @staticmethod
    def _item_screen(cart_text, visual_hash):
        return ScreenObservation(
            (
                ObservedElement(
                    "커피", Rect(5, 5, 45, 30), source="uia", role="ButtonControl"
                ),
                ObservedElement(
                    "아이스 아메리카노",
                    Rect(10, 70, 90, 120),
                    source="uia",
                    role="ListItemControl",
                ),
                ObservedElement(
                    cart_text,
                    Rect(120, 20, 195, 55),
                    source="uia",
                    role="TextControl",
                ),
            ),
            200,
            300,
            visual_hash=visual_hash,
        )

    def test_item_addition_requires_semantic_cart_delta(self):
        before = self._item_screen("총 수량 0개", "before")
        animation_only = self._item_screen("총 수량 0개", "after")
        replay = ReplayObserver(
            [before, before, animation_only, animation_only, animation_only],
            invoke=False,
        )
        nav = Navigator(
            SimpleNamespace(category_centers={"커피": (10, 10)}, name_to_entry={}),
            config(),
            observer=replay,
            profile=profile(),
            pointer=lambda _x, _y: None,
            sleeper=lambda _: None,
        )
        item = ResolvedOrderItem(
            "아메리카노",
            MenuRecord("아이스 아메리카노", "커피", 1, (50, 100)),
            1,
        )

        self.assertFalse(nav.add_resolved_item(item))
        self.assertIn("cart contents", nav.last_error)
        self.assertTrue(nav.last_uncertain)

    def test_item_addition_accepts_stable_cart_quantity_change(self):
        before = self._item_screen("총 수량 0개", "before")
        after = self._item_screen("총 수량 1개", "after")
        replay = ReplayObserver([before, before, after, after, after], invoke=False)
        nav = Navigator(
            SimpleNamespace(category_centers={"커피": (10, 10)}, name_to_entry={}),
            config(),
            observer=replay,
            profile=profile(),
            pointer=lambda _x, _y: None,
            sleeper=lambda _: None,
        )
        item = ResolvedOrderItem(
            "아메리카노",
            MenuRecord("아이스 아메리카노", "커피", 1, (50, 100)),
            1,
        )

        self.assertTrue(nav.add_resolved_item(item))

    def test_unpinned_live_runtime_is_rejected_before_observation(self):
        with self.assertRaises(ValueError):
            Navigator(
                SimpleNamespace(category_centers={}, name_to_entry={}),
                config(kiosk_window_title=""),
                profile=profile(),
            )

    def test_page_does_not_advance_when_screen_and_target_page_evidence_do_not_change(self):
        unchanged = ScreenObservation(
            (
                ObservedElement(
                    "다음", Rect(10, 220, 80, 270), source="uia", role="ButtonControl"
                ),
                # A cart line must not prove that page 2 is visible in the menu region.
                ObservedElement(
                    "페이지2 메뉴", Rect(130, 20, 195, 60), source="uia", role="TextControl"
                ),
            ),
            200,
            300,
            visual_hash="same",
        )
        replay = ReplayObserver([unchanged], invoke=False)
        index = SimpleNamespace(
            category_centers={"커피": (10, 10)},
            name_to_entry={
                "페이지1 메뉴": ("커피", 1, (20, 100)),
                "페이지2 메뉴": ("커피", 2, (20, 100)),
            },
            next_xy=(50, 250),
        )
        nav = Navigator(
            index,
            config(),
            observer=replay,
            profile=profile(),
            pointer=lambda _x, _y: None,
            sleeper=lambda _: None,
        )

        self.assertFalse(nav.go_page_from_one("커피", 2))
        self.assertEqual(nav.current_page, 1)


if __name__ == "__main__":
    unittest.main()
