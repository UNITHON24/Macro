import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "macro_pkg" / "macro"))

from acceptance_kiosk import load_acceptance_spec, run_acceptance  # noqa: E402
from voice.index_loader import MenuIndex  # noqa: E402
from voice.kiosk_profile import KioskProfile  # noqa: E402
from voice.perception import ObservedElement, Rect, ScreenObservation  # noqa: E402


class KioskAcceptanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = ROOT / "macro_pkg" / "settingPack"
        index = MenuIndex(
            str(settings / "kiosk_ui_coords_easyocr.json"),
            str(settings / "menu_cards.json"),
        )
        cls.profile = KioskProfile.load(str(settings / "kiosk_profile.json"), index)
        cls.spec = load_acceptance_spec(ROOT / "acceptance" / "unithon-demo.v1.json")

    def test_checked_in_profile_is_ready_but_not_claimed_as_physical_acceptance(self):
        report = run_acceptance(self.spec, self.profile)

        self.assertEqual(report["overall_status"], "profile_ready")
        self.assertEqual(report["profile_contract"]["status"], "pass")
        self.assertTrue(all(case["status"] == "pass" for case in report["order_cases"]))
        self.assertEqual(report["live_observation"]["status"], "not_run")

    def test_read_only_live_observation_can_pass_the_explicit_contract(self):
        observation = ScreenObservation(
            elements=(
                ObservedElement("커피", Rect(10, 10, 100, 50), source="uia"),
                ObservedElement("음료", Rect(110, 10, 200, 50), source="uia"),
                ObservedElement("디저트", Rect(210, 10, 300, 50), source="uia"),
            ),
            width=1080,
            height=1920,
        )

        report = run_acceptance(
            self.spec,
            self.profile,
            observation,
            {"status": "pass", "sample_rate": 16000, "channels": 1},
        )

        self.assertEqual(report["overall_status"], "passed")
        self.assertEqual(report["live_observation"]["detected_state"], "menu")

    def test_unknown_provider_and_viewport_fail_closed(self):
        observation = ScreenObservation(
            elements=(ObservedElement("커피", Rect(0, 0, 10, 10), source="fixture"),),
            width=800,
            height=600,
        )

        report = run_acceptance(
            self.spec,
            self.profile,
            observation,
            {"status": "fail", "sample_rate": 16000, "channels": 1},
        )

        self.assertEqual(report["overall_status"], "failed")
        self.assertIn(
            "no accepted UIA/OCR provider produced evidence",
            report["live_observation"]["errors"],
        )
        self.assertIn(
            "screen dimensions do not match an accepted kiosk viewport",
            report["live_observation"]["errors"],
        )

    def test_required_microphone_capability_fails_closed_when_not_probed(self):
        observation = ScreenObservation(
            elements=(ObservedElement("커피", Rect(0, 0, 10, 10), source="uia"),),
            width=1080,
            height=1920,
        )

        report = run_acceptance(self.spec, self.profile, observation)

        self.assertEqual(report["overall_status"], "failed")
        self.assertIn(
            "default microphone did not pass the read-only capability probe",
            report["live_observation"]["errors"],
        )

    def test_requested_live_observation_cannot_fall_back_to_profile_ready(self):
        report = run_acceptance(
            self.spec,
            self.profile,
            observation=None,
            microphone={"status": "pass", "sample_rate": 16000, "channels": 1},
            live_requested=True,
        )

        self.assertEqual(report["overall_status"], "failed")
        self.assertEqual(report["live_observation"]["status"], "fail")
        self.assertIn(
            "screen observation failed before acceptance evidence was available",
            report["errors"],
        )

    def test_profile_contract_drift_is_reported(self):
        spec = deepcopy(self.spec)
        spec["profile"]["required_aliases"].append("missing-control")

        report = run_acceptance(spec, self.profile)

        self.assertEqual(report["overall_status"], "failed")
        self.assertIn("missing profile aliases: missing-control", report["errors"])

    def test_invalid_spec_schema_is_rejected(self):
        path = ROOT / "acceptance" / "unithon-demo.v1.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["schema_version"] = 99
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.json"
            invalid.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_acceptance_spec(invalid)


if __name__ == "__main__":
    unittest.main()
