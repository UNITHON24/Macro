import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "macro_pkg" / "macro"))

from voice.errors import GroundingError  # noqa: E402
from voice.grounding import Target, ground_target, scale_point  # noqa: E402
from voice.perception import (  # noqa: E402
    HybridScreenObserver,
    ObservedElement,
    Rect,
    ScreenObservation,
    UIAutomationProvider,
)
from voice.transition_graph import Transition, TransitionGraph  # noqa: E402


def observation(*elements, visual_hash="a"):
    return ScreenObservation(tuple(elements), 1000, 1600, visual_hash=visual_hash)


class GroundingTest(unittest.TestCase):
    def test_uia_wins_over_duplicate_ocr_detection(self):
        ocr = ObservedElement("결제하기", Rect(10, 10, 110, 60), source="ocr", confidence=0.91)
        uia = ObservedElement("결제하기", Rect(11, 11, 111, 61), role="ButtonControl", source="uia")

        result = ground_target(observation(ocr, uia), Target("checkout", ("결제하기",)))

        self.assertEqual(result.element.source, "uia")

    def test_two_equal_controls_fail_as_ambiguous(self):
        first = ObservedElement("확인", Rect(10, 10, 80, 50), source="uia")
        second = ObservedElement("확인", Rect(600, 10, 670, 50), source="uia")

        with self.assertRaises(GroundingError):
            ground_target(observation(first, second), Target("confirm", ("확인",)))

    def test_exact_action_label_beats_nested_fixture_button(self):
        card = ObservedElement(
            "아이스 아메리카노 장바구니에 추가",
            Rect(100, 100, 500, 600),
            role="ListItemControl",
            source="uia",
        )
        nested_button = ObservedElement(
            "아이스 아메리카노 추가",
            Rect(400, 500, 480, 580),
            role="ButtonControl",
            source="uia",
        )

        result = ground_target(
            observation(card, nested_button),
            Target(
                "menu:아이스 아메리카노",
                (
                    "아이스 아메리카노 장바구니에 추가",
                    "아이스 아메리카노",
                ),
                roles=("ListItemControl", "ButtonControl"),
            ),
        )

        self.assertEqual(result.element, card)

    def test_action_role_beats_non_action_text_with_same_label(self):
        label = ObservedElement(
            "아메리카노",
            Rect(100, 100, 300, 160),
            role="TextControl",
            source="uia",
        )
        button = ObservedElement(
            "아메리카노",
            Rect(400, 100, 500, 200),
            role="ButtonControl",
            source="uia",
        )

        result = ground_target(
            observation(label, button),
            Target("menu:아메리카노", ("아메리카노",), roles=("ButtonControl",)),
        )

        self.assertEqual(result.element, button)

    def test_coordinate_fallback_scales_to_current_viewport(self):
        self.assertEqual(scale_point((540, 960), (1080, 1920), (2160, 3840)), (1080, 1920))

    def test_visual_change_is_part_of_observation_signature(self):
        element = ObservedElement("커피", Rect(10, 10, 60, 40), source="ocr")
        self.assertNotEqual(
            observation(element, visual_hash="before").signature,
            observation(element, visual_hash="after").signature,
        )

    def test_transition_graph_detects_state_and_finds_shortest_path(self):
        graph = TransitionGraph(
            {"menu": ("커피",), "payment": ("카드를 넣어주세요",)},
            [
                Transition("menu", "method", Target("checkout", ("결제",)), ("카드",)),
                Transition("method", "payment", Target("card", ("카드",)), ("카드를 넣어주세요",)),
            ],
        )
        screen = observation(ObservedElement("커피", Rect(1, 1, 10, 10)))

        self.assertEqual(graph.detect_state(screen), "menu")
        self.assertEqual([step.target.key for step in graph.path("menu", "payment")], ["checkout", "card"])

    def test_short_payment_method_label_does_not_satisfy_ready_marker(self):
        graph = TransitionGraph(
            {"payment_method": ("카드",), "payment_ready": ("카드를 넣어주세요",)},
            [],
        )
        method = observation(ObservedElement("카드", Rect(1, 1, 20, 20)))

        self.assertEqual(graph.detect_state(method), "payment_method")

    def test_hybrid_provider_configuration_is_constructed_without_live_imports(self):
        provider = HybridScreenObserver(
            SimpleNamespace(
                kiosk_window_title="",
                uia_enabled=False,
                ocr_enabled=False,
            )
        )

        self.assertIsNone(provider.uia)
        self.assertIsNone(provider.ocr)

    def test_uia_provider_binds_the_exact_native_window_handle(self):
        expected = SimpleNamespace(NativeWindowHandle=8123)
        automation = SimpleNamespace(ControlFromHandle=lambda handle: expected)
        provider = UIAutomationProvider("Kiosk")
        provider.bind_window(8123)

        self.assertIs(provider._root(automation), expected)

    def test_uia_provider_rejects_offscreen_and_disabled_controls(self):
        self.assertFalse(
            UIAutomationProvider._visible_and_enabled(
                SimpleNamespace(IsOffscreen=True, IsEnabled=True)
            )
        )
        self.assertFalse(
            UIAutomationProvider._visible_and_enabled(
                SimpleNamespace(IsOffscreen=False, IsEnabled=False)
            )
        )
        self.assertTrue(
            UIAutomationProvider._visible_and_enabled(
                SimpleNamespace(IsOffscreen=False, IsEnabled=True)
            )
        )


if __name__ == "__main__":
    unittest.main()
