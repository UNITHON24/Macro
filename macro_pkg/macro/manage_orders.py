#!/usr/bin/env python3
"""Inspect and resolve orders only after checking the physical kiosk state."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from voice.order_queue import OrderQueue


def queue_path() -> str:
    return os.environ.get(
        "KIOSK_ORDER_DB",
        str(Path.home() / ".macro" / "orders.sqlite3"),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    list_parser = subcommands.add_parser("list", help="최근 주문 상태 표시")
    list_parser.add_argument("--limit", type=int, default=50)

    resolve_parser = subcommands.add_parser(
        "resolve", help="claimed/awaiting_handoff/uncertain 주문에 운영자 판단 기록"
    )
    resolve_parser.add_argument("order_id")
    resolve_parser.add_argument("resolution", choices=("succeeded", "failed", "requeue"))
    resolve_parser.add_argument(
        "--side-effects-checked",
        action="store_true",
        help="실제 장바구니 상태를 확인했음을 명시",
    )
    args = parser.parse_args(argv)
    orders = OrderQueue(queue_path())

    if args.command == "list":
        print(json.dumps(orders.list_orders(args.limit), ensure_ascii=False, indent=2))
        return 0
    if not args.side_effects_checked:
        parser.error("resolve에는 실제 키오스크 상태 확인 후 --side-effects-checked가 필요합니다")
    try:
        status = orders.resolve_uncertain(args.order_id, args.resolution)
    except (KeyError, ValueError) as exc:
        print(f"[ERROR] {exc}")
        return 1
    print(json.dumps({"order_id": args.order_id, "status": status}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
