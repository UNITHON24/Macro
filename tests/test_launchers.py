import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class LauncherPathTest(unittest.TestCase):
    def test_full_launcher_points_to_tracked_client_files(self):
        launcher = load_module("macro_launcher", ROOT / "macro_pkg" / "launcher.py")

        self.assertTrue(launcher.FIRST.is_file())
        self.assertTrue(launcher.ORDERS.is_file())
        self.assertTrue(launcher.RUN_VOICE.is_file())

    def test_full_launcher_skips_calibration_by_default(self):
        launcher = load_module("macro_launcher_safe_default", ROOT / "macro_pkg" / "launcher.py")

        with patch.dict(
            os.environ, {"KIOSK_ORDER_TOKEN": "a" * 32}, clear=True
        ), patch.object(launcher, "run_sync") as run_sync:
            prepared = launcher.prepare_client_files()

        self.assertTrue(prepared)
        run_sync.assert_not_called()

    def test_full_launcher_propagates_calibration_failure(self):
        launcher = load_module("macro_launcher_calibration_failure", ROOT / "macro_pkg" / "launcher.py")

        with patch.dict(os.environ, {"KIOSK_RUN_CALIBRATION": "1"}, clear=True), patch.object(
            launcher, "run_sync", return_value=7
        ) as run_sync:
            prepared = launcher.prepare_client_files()

        self.assertFalse(prepared)
        run_sync.assert_called_once()

    def test_external_backend_launcher_points_to_tracked_client_files(self):
        launcher = load_module(
            "macro_launcher_without_backend", ROOT / "macro_pkg" / "launcherNonback.py"
        )

        self.assertTrue(launcher.FIRST.is_file())
        self.assertTrue(launcher.ORDERS.is_file())
        self.assertTrue(launcher.RUN_VOICE.is_file())

    def test_external_backend_launcher_skips_calibration_by_default(self):
        launcher = load_module(
            "macro_launcher_without_backend_safe_default",
            ROOT / "macro_pkg" / "launcherNonback.py",
        )

        with patch.dict(
            os.environ, {"KIOSK_ORDER_TOKEN": "a" * 32}, clear=True
        ), patch.object(launcher, "run_sync") as run_sync:
            prepared = launcher.prepare_client_files()

        self.assertTrue(prepared)
        run_sync.assert_not_called()

    def test_launcher_rejects_a_missing_order_hub_token(self):
        launcher = load_module(
            "macro_launcher_missing_token", ROOT / "macro_pkg" / "launcherNonback.py"
        )

        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(launcher.prepare_client_files())


if __name__ == "__main__":
    unittest.main()
