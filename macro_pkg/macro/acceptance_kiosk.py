#!/usr/bin/env python3
"""Read-only acceptance runner for one reviewed black-box kiosk profile."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from voice.config import Config
from voice.index_loader import MenuIndex
from voice.kiosk_profile import KioskProfile
from voice.perception import HybridScreenObserver, ScreenObservation


def load_acceptance_spec(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("unsupported acceptance spec schema")
    if not str(data.get("id", "")).strip():
        raise ValueError("acceptance spec id is required")
    if not isinstance(data.get("profile"), dict):
        raise ValueError("acceptance profile contract is required")
    if not isinstance(data.get("order_cases"), list) or not data["order_cases"]:
        raise ValueError("at least one order acceptance case is required")
    if not isinstance(data.get("live_observation"), dict):
        raise ValueError("live observation contract is required")
    return data


def _check_profile(spec: Mapping[str, Any], profile: KioskProfile) -> list[str]:
    contract = spec["profile"]
    errors: list[str] = []
    if profile.data.get("name") != contract.get("name"):
        errors.append("profile name does not match acceptance spec")
    if profile.data.get("schema_version") != contract.get("schema_version"):
        errors.append("profile schema does not match acceptance spec")

    states = set((profile.data.get("states") or {}).keys())
    missing_states = sorted(set(contract.get("required_states", ())) - states)
    if missing_states:
        errors.append(f"missing profile states: {', '.join(missing_states)}")

    aliases = set(profile.aliases)
    missing_aliases = sorted(set(contract.get("required_aliases", ())) - aliases)
    if missing_aliases:
        errors.append(f"missing profile aliases: {', '.join(missing_aliases)}")
    return errors


def _check_orders(spec: Mapping[str, Any], profile: KioskProfile) -> tuple[list[dict], list[str]]:
    results: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for case in spec["order_cases"]:
        case_id = str(case.get("id", "")).strip()
        if not case_id or case_id in seen:
            errors.append("order acceptance case ids must be present and unique")
            continue
        seen.add(case_id)
        try:
            resolved = profile.resolve_order_item(case.get("input", {}))
            actual = {
                "menu": resolved.menu.name,
                "quantity": resolved.quantity,
                "options": [target.key for target in resolved.option_targets],
            }
            expected = case.get("expected", {})
            passed = actual == expected
            if not passed:
                errors.append(f"order case {case_id} did not match expected semantics")
            results.append(
                {
                    "id": case_id,
                    "status": "pass" if passed else "fail",
                    "expected": expected,
                    "actual": actual,
                }
            )
        except Exception as exc:  # profile errors are acceptance evidence, not a traceback
            errors.append(f"order case {case_id} could not be resolved: {type(exc).__name__}")
            results.append({"id": case_id, "status": "fail"})
    return results, errors


def _viewport_matches(contract: Mapping[str, Any], observation: ScreenObservation) -> bool:
    tolerance = float(contract.get("dimension_tolerance", 0))
    for expected in contract.get("accepted_viewports", ()):
        width = int(expected["width"])
        height = int(expected["height"])
        if (
            abs(observation.width - width) <= width * tolerance
            and abs(observation.height - height) <= height * tolerance
        ):
            return True
    return False


def _check_live_observation(
    spec: Mapping[str, Any],
    profile: KioskProfile,
    observation: ScreenObservation,
    microphone: Optional[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    contract = spec["live_observation"]
    errors: list[str] = []
    providers = sorted({element.source.casefold() for element in observation.elements})
    accepted_providers = {str(value).casefold() for value in contract.get("provider_any", ())}
    if not accepted_providers.intersection(providers):
        errors.append("no accepted UIA/OCR provider produced evidence")
    if len(observation.elements) < int(contract.get("minimum_elements", 1)):
        errors.append("too few visible elements were observed")
    if not _viewport_matches(contract, observation):
        errors.append("screen dimensions do not match an accepted kiosk viewport")

    state = profile.transition_graph().detect_state(observation)
    if state not in set(contract.get("accepted_states", ())):
        errors.append("current kiosk state is unknown or not accepted")
    microphone_contract = contract.get("microphone", {})
    if microphone_contract.get("required") and (
        not microphone or microphone.get("status") != "pass"
    ):
        errors.append("default microphone did not pass the read-only capability probe")
    return (
        {
            "status": "pass" if not errors else "fail",
            "screen": {"width": observation.width, "height": observation.height},
            "providers": providers,
            "detected_state": state,
            "element_count": len(observation.elements),
            "microphone": microphone or {"status": "not_run"},
            "errors": errors,
        },
        errors,
    )


def run_acceptance(
    spec: Mapping[str, Any],
    profile: KioskProfile,
    observation: Optional[ScreenObservation] = None,
    microphone: Optional[Mapping[str, Any]] = None,
    live_requested: bool = False,
) -> dict[str, Any]:
    profile_errors = _check_profile(spec, profile)
    order_results, order_errors = _check_orders(spec, profile)
    errors = [*profile_errors, *order_errors]

    if observation is None and live_requested:
        live_errors = ["screen observation failed before acceptance evidence was available"]
        if spec["live_observation"].get("microphone", {}).get("required") and (
            not microphone or microphone.get("status") != "pass"
        ):
            live_errors.append("default microphone did not pass the read-only capability probe")
        errors.extend(live_errors)
        live = {
            "status": "fail",
            "microphone": microphone or {"status": "not_run"},
            "errors": live_errors,
        }
        overall = "failed"
    elif observation is None:
        live = {
            "status": "not_run",
            "reason": "physical Windows kiosk observation was not requested",
        }
        overall = "profile_ready" if not errors else "failed"
    else:
        live, live_errors = _check_live_observation(spec, profile, observation, microphone)
        errors.extend(live_errors)
        overall = "passed" if not errors else "failed"

    return {
        "acceptance_spec": spec["id"],
        "mode": "read_only",
        "overall_status": overall,
        "profile_contract": {
            "status": "pass" if not profile_errors else "fail",
            "errors": profile_errors,
        },
        "order_cases": order_results,
        "live_observation": live,
        "errors": errors,
        "limitations": [
            "No clicks, pointer movement, microphone input, or payment action are performed.",
            "profile_ready is not a physical-kiosk acceptance pass.",
        ],
    }


def probe_default_microphone(sample_rate: int, channels: int) -> dict[str, Any]:
    """Check input capability without opening a stream or recording audio."""
    try:
        import sounddevice as sd

        device = sd.query_devices(kind="input")
        sd.check_input_settings(
            device=device["index"], samplerate=sample_rate, channels=channels, dtype="int16"
        )
        return {
            "status": "pass",
            "max_input_channels": int(device["max_input_channels"]),
            "sample_rate": sample_rate,
            "channels": channels,
        }
    except Exception:
        return {
            "status": "fail",
            "sample_rate": sample_rate,
            "channels": channels,
        }


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="프로필 계약을 검증하고, 선택적으로 실제 키오스크를 읽기 전용 관찰합니다."
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=root / "acceptance" / "unithon-demo.v1.json",
        help="acceptance spec JSON 경로",
    )
    parser.add_argument("--observe", action="store_true", help="현재 Windows 키오스크를 읽기 전용 관찰")
    parser.add_argument("--output", type=Path, help="결과 JSON 저장 경로")
    args = parser.parse_args(argv)

    config = Config()
    index = MenuIndex(config.ui_coords_path, config.menu_cards_path)
    profile = KioskProfile.load(config.profile_path, index)
    spec = load_acceptance_spec(args.spec)
    observation = None
    if args.observe:
        try:
            observation = HybridScreenObserver(config).observe()
        except Exception:
            observation = None
    microphone = None
    if args.observe:
        microphone_contract = spec["live_observation"].get("microphone", {})
        microphone = probe_default_microphone(
            int(microphone_contract.get("sample_rate", config.sample_rate)),
            int(microphone_contract.get("channels", 1)),
        )
    report = run_acceptance(
        spec,
        profile,
        observation,
        microphone,
        live_requested=args.observe,
    )
    report["generated_at"] = datetime.now(timezone.utc).isoformat()

    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["overall_status"] in {"profile_ready", "passed"} else 2


if __name__ == "__main__":
    sys.exit(main())
