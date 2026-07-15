#!/usr/bin/env python3
"""Read-only compatibility check for an existing black-box kiosk screen."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from voice.config import Config
from voice.index_loader import MenuIndex
from voice.kiosk_profile import KioskProfile
from voice.perception import HybridScreenObserver


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="UI Automation/OCR로 현재 화면을 읽되 클릭은 수행하지 않습니다."
    )
    parser.add_argument("--output", help="관찰 결과 JSON 저장 경로")
    parser.add_argument("--resolve-order", help="주문 항목 JSON의 의미 해석만 검사")
    args = parser.parse_args(argv)

    config = Config()
    index = MenuIndex(config.ui_coords_path, config.menu_cards_path)
    profile = KioskProfile.load(config.profile_path, index)

    if args.resolve_order:
        raw = json.loads(args.resolve_order)
        resolved = profile.resolve_order_item(raw)
        print(
            json.dumps(
                {
                    "requested_name": resolved.requested_name,
                    "resolved_menu": resolved.menu.name,
                    "category": resolved.menu.category,
                    "page": resolved.menu.page,
                    "quantity": resolved.quantity,
                    "options": [target.key for target in resolved.option_targets],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    observation = HybridScreenObserver(config).observe()
    payload = {
        "screen": {"width": observation.width, "height": observation.height},
        "providers": sorted({element.source for element in observation.elements}),
        "detected_state": profile.transition_graph().detect_state(observation),
        "elements": [
            {
                "text": element.text,
                "role": element.role,
                "source": element.source,
                "confidence": round(element.confidence, 3),
                "center": list(element.rect.center),
            }
            for element in observation.elements
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(encoded + "\n", encoding="utf-8")
        print(f"관찰 결과 저장: {args.output}")
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    sys.exit(main())
