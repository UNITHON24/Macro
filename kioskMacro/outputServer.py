#!/usr/bin/env python3
"""
outputServer.py
- 매크로 서버(http://localhost:9999/api/orders)에 테스트 주문을 보내는 간단 서버/스크립트
- 기능: 실행 후 즉시 "생강차 1개"를 담아달라는 JSON을 POST 전송
- 매크로 서버(run_voice.py 내부 OrdersClient)가 해당 JSON을 받아 메뉴명만 추출해 실제 매크로를 실행

실행: python outputServer.py
"""

import json
import logging
import requests
from datetime import datetime

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("outputServer")

MACRO_ORDERS_URL = "http://localhost:9999/api/orders"

def send_order(menu: str, count: int = 1):
    """단일 아이템 주문 전송(호환 유지)."""
    return send_bulk_order([{"name": menu, "count": count}])

def send_bulk_order(items: list[dict]):
    """복수 아이템 주문 전송.
    items 예: [{"name":"망고 스무디","count":1}, {"name":"초코칩 쿠키","count":3}]
    """
    payload = {
        "type": "final",
        "items": items,
        "timestamp": datetime.now().isoformat()
    }
    logger.info(f"[HTTP] send order -> {MACRO_ORDERS_URL}\n{json.dumps(payload, ensure_ascii=False)}")
    r = requests.post(MACRO_ORDERS_URL, json=payload, timeout=3)
    logger.info(f"[HTTP] status={r.status_code} body={r.text}")
    return r

if __name__ == "__main__":
    try:
        send_bulk_order([
            {"name": "레드벨벳 케이크", "count": 1},
            {"name": "초코칩 쿠키", "count": 3},
            {"name": "초콜릿 브라우니", "count": 2},
            {"name": "뉴욕 치즈 케이크", "count": 2},
        ])
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.exception(e)
