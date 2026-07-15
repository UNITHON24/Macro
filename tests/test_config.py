import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "macro_pkg" / "macro"))

from voice.config import Config  # noqa: E402


class ConfigTest(unittest.TestCase):
    def test_pointer_and_checkout_actions_are_safe_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            config = Config()

        self.assertTrue(config.dry_run)
        self.assertFalse(config.allow_payment_navigation)
        self.assertFalse(config.allow_coordinate_fallback)
        self.assertEqual(config.max_order_items, 10)
        self.assertEqual(config.max_item_quantity, 10)
        self.assertEqual(
            Path(config.ui_coords_path).parts[-3:],
            ("macro_pkg", "settingPack", "kiosk_ui_coords_easyocr.json"),
        )
        self.assertEqual(
            Path(config.menu_cards_path).parts[-3:],
            ("macro_pkg", "settingPack", "menu_cards.json"),
        )
        self.assertEqual(
            Path(config.profile_path).parts[-3:],
            ("macro_pkg", "settingPack", "kiosk_profile.json"),
        )

    def test_environment_is_evaluated_for_each_instance(self):
        with patch.dict(
            os.environ,
            {"KIOSK_DRY_RUN": "0", "KIOSK_ALLOW_CHECKOUT": "true"},
            clear=True,
        ):
            live_config = Config()

        with patch.dict(os.environ, {}, clear=True):
            safe_config = Config()

        self.assertFalse(live_config.dry_run)
        self.assertTrue(live_config.allow_payment_navigation)
        self.assertTrue(safe_config.dry_run)
        self.assertFalse(safe_config.allow_payment_navigation)

    def test_invalid_or_empty_boolean_values_preserve_safe_defaults(self):
        with patch.dict(
            os.environ,
            {"KIOSK_DRY_RUN": "typo", "KIOSK_ALLOW_CHECKOUT": ""},
            clear=True,
        ):
            config = Config()

        self.assertTrue(config.dry_run)
        self.assertFalse(config.allow_checkout)

    def test_order_limits_are_configurable(self):
        with patch.dict(
            os.environ,
            {"KIOSK_MAX_ORDER_ITEMS": "4", "KIOSK_MAX_ITEM_QUANTITY": "3"},
            clear=True,
        ):
            config = Config()

        self.assertEqual(config.max_order_items, 4)
        self.assertEqual(config.max_item_quantity, 3)

    def test_invalid_order_limits_preserve_safe_defaults(self):
        with patch.dict(
            os.environ,
            {"KIOSK_MAX_ORDER_ITEMS": "typo", "KIOSK_MAX_ITEM_QUANTITY": "0"},
            clear=True,
        ):
            config = Config()

        self.assertEqual(config.max_order_items, 10)
        self.assertEqual(config.max_item_quantity, 10)


if __name__ == "__main__":
    unittest.main()
