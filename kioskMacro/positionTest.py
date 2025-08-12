#!/usr/bin/env python3
"""
positionTest.py
- 설정 JSON(kiosk_ui_coords_easyocr.json, menu_cards.json)을 읽어 모든 메뉴의 중심 좌표를 한 번씩 클릭
- 각 클릭 사이에 1초 대기
- 주의: 실제로 마우스가 움직이고 클릭합니다. 테스트는 KIOSK_DRY_RUN=1로 안전하게 가능.

실행:
  python positionTest.py
환경변수(선택):
  KIOSK_DRY_RUN=1  안전 모드(클릭 대신 로그만)
"""

import os
import time
import pyautogui
from voice.config import Config
from voice.index_loader import MenuIndex
from voice.navigator import Navigator


def main():
    cfg = Config()
    # 모든 클릭 사이 휴식 시간을 0.3초로 통일
    cfg.item_click_delay = 0.3
    cfg.page_click_delay = 0.3
    cfg.cat_click_delay = 0.3

    index = MenuIndex(cfg.ui_coords_path, cfg.menu_cards_path)
    nav = Navigator(index, cfg)

    # 모든 메뉴를 menu_cards.json 순서대로 순회
    names = list(index.name_to_entry.keys())
    print(f"[TEST] 총 {len(names)}개 메뉴 클릭 테스트 시작 (menu_cards.json 순서)")

    # 카테고리/페이지를 고려하여 해당 위치로 이동 후 글자 중심 좌표를 클릭
    for i, name in enumerate(names, 1):
        cat, page, xy = index.name_to_entry[name]
        print(f"[TEST] {i}/{len(names)} '{name}' / {cat} p{page} @ {xy}")

        # 카테고리 이동 → 페이지 이동 → 글자 좌표 클릭
        print(f"  → 카테고리 '{cat}' 클릭 중...")
        if not nav.go_category(cat):
            print(f"[TEST] 카테고리 이동 실패: {cat}")
            continue
        print(f"  ✓ 카테고리 '{cat}' 클릭 완료")
        time.sleep(cfg.cat_click_delay)

        print(f"  → 페이지 {page} 클릭 중...")
        if not nav.go_page_from_one(page):
            print(f"[TEST] 페이지 이동 실패: p{page}")
            continue
        print(f"  ✓ 페이지 {page} 클릭 완료")
        time.sleep(cfg.page_click_delay)

        print(f"  → 메뉴 '{name}' 클릭 중... (좌표: {xy})")
        nav.click(xy)
        print(f"  ✓ 메뉴 '{name}' 클릭 완료")
        time.sleep(cfg.item_click_delay)

    print("[TEST] 완료")


if __name__ == "__main__":
    main()
