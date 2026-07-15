import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "macro_pkg" / "macro"))

from voice.errors import ProfileError  # noqa: E402
from voice.index_loader import MenuIndex  # noqa: E402
from voice.kiosk_profile import KioskProfile  # noqa: E402


class KioskProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = ROOT / "macro_pkg" / "settingPack"
        index = MenuIndex(
            str(settings / "kiosk_ui_coords_easyocr.json"),
            str(settings / "menu_cards.json"),
        )
        cls.profile = KioskProfile.load(str(settings / "kiosk_profile.json"), index)

    def test_temperature_disambiguates_generic_menu_name(self):
        iced = self.profile.resolve_order_item(
            {
                "menuName": "americano",
                "displayName": "아메리카노",
                "temperature": "ICE",
                "quantity": 2,
            }
        )
        hot = self.profile.resolve_order_item(
            {"menuName": "아메리카노", "temperature": "HOT", "quantity": 1}
        )

        self.assertEqual(iced.menu.name, "아이스 아메리카노")
        self.assertEqual(hot.menu.name, "따뜻한 아메리카노")
        self.assertEqual(iced.quantity, 2)
        self.assertEqual(iced.option_targets, ())

    def test_backend_internal_menu_code_does_not_override_visible_name(self):
        item = self.profile.resolve_order_item(
            {"menuName": "cafe_latte", "displayName": "카페 라떼", "quantity": 1}
        )

        self.assertEqual(item.menu.name, "카페 라떼")

    def test_generic_temperature_variant_without_temperature_fails_closed(self):
        with self.assertRaises(ProfileError):
            self.profile.resolve_order_item({"menuName": "아메리카노", "quantity": 1})

    def test_size_becomes_a_visible_option_when_not_encoded_in_menu(self):
        item = self.profile.resolve_order_item(
            {"menuName": "카페 라떼", "size": "LARGE", "quantity": 1}
        )

        self.assertEqual(item.menu.name, "카페 라떼")
        self.assertEqual([target.key for target in item.option_targets], ["size:LARGE"])

    def test_conflicting_name_and_temperature_are_rejected(self):
        with self.assertRaises(ProfileError):
            self.profile.resolve_order_item(
                {"menuName": "아이스 아메리카노", "temperature": "HOT"}
            )


if __name__ == "__main__":
    unittest.main()
