import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "macro_pkg" / "settingPack"))

from ocr_geometry import restore_polygon  # noqa: E402


class OCRGeometryTest(unittest.TestCase):
    def test_resized_ocr_polygon_returns_to_capture_coordinates(self):
        polygon = [[16, 32], [160, 32], [160, 96], [16, 96]]

        self.assertEqual(
            restore_polygon(polygon, 1.6),
            [[10.0, 20.0], [100.0, 20.0], [100.0, 60.0], [10.0, 60.0]],
        )

    def test_non_positive_scale_is_rejected(self):
        with self.assertRaises(ValueError):
            restore_polygon([[1, 1]], 0)


if __name__ == "__main__":
    unittest.main()
