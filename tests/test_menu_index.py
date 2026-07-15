import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "macro_pkg" / "macro"))

from voice.index_loader import MenuIndex  # noqa: E402


class MenuIndexTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.ui_path = root / "ui.json"
        self.menu_path = root / "menu.json"
        self.ui_path.write_text(
            json.dumps(
                {
                    "categories": [{"name": "커피", "center": {"x": 100, "y": 200}}],
                    "nav_buttons": {
                        "prev": {"center": {"x": 10, "y": 20}},
                        "next": {"center": {"x": 30, "y": 40}},
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.menu_path.write_text(
            json.dumps(
                [
                    {
                        "name": "아이스 아메리카노",
                        "category": "커피",
                        "page": 1,
                        "center": {"x": 300, "y": 400},
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_loads_navigation_and_exact_menu_coordinates(self):
        index = MenuIndex(str(self.ui_path), str(self.menu_path))

        self.assertEqual(index.category_centers["커피"], (100, 200))
        self.assertEqual(index.prev_xy, (10, 20))
        self.assertEqual(index.next_xy, (30, 40))
        self.assertEqual(
            index.find_menu_best("아이스 아메리카노"),
            ("아이스 아메리카노", "커피", 1, (300, 400)),
        )

    def test_normalized_menu_name_can_match(self):
        index = MenuIndex(str(self.ui_path), str(self.menu_path))

        self.assertEqual(
            index.find_menu_best("아이스아메리카노"),
            ("아이스 아메리카노", "커피", 1, (300, 400)),
        )


if __name__ == "__main__":
    unittest.main()
