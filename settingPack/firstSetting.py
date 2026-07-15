#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
키오스크 메뉴 분석 전체 파이프라인
1. openKiosk.py로 키오스크 열기
2. ocrFirst.py로 카테고리와 이전/다음 버튼 위치 파악
3. kioskMenuCapture.py로 메뉴들 사진 찍기
4. kioskAnalyzeEasyOCR.py로 분석해서 JSON 파일로 저장
"""

import os
import sys
import time
import subprocess
import pyautogui

# pyautogui 안전장치 비활성화
pyautogui.FAILSAFE = True

def run_command(cmd):
    """명령어 실행"""
    print(f"\n{'='*50}")
    print(f"실행: {cmd}")
    print(f"{'='*50}")

    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        if result.stdout:
            print("출력:", result.stdout)
        if result.stderr:
            print("오류:", result.stderr)
        return result.returncode == 0
    except Exception as e:
        print(f"실행 오류: {e}")
        return False

def main():
    print("🎯 키오스크 메뉴 분석 파이프라인 시작")
    print(f"작업 디렉토리: {os.getcwd()}")

    # 마우스를 화면 오른쪽 끝으로 이동
    try:
        screen_width, screen_height = pyautogui.size()
        safe_x = screen_width - 10  # 화면 가장 오른쪽
        safe_y = screen_height // 2  # 화면 중앙 높이
        pyautogui.moveTo(safe_x, safe_y, duration=0.5)
        print(f"🖱️ 마우스를 안전한 위치로 이동: ({safe_x}, {safe_y})")
    except Exception as e:
        print(f"마우스 이동 오류: {e}")

    # 필요한 파일 확인
    required_files = ["openKiosk.py", "ocrFirst.py", "kioskMenuCapture.py", "kioskAnalyzeEasyOCR.py"]
    for file in required_files:
        if not os.path.exists(file):
            print(f"❌ 파일 없음: {file}")
            return

    print("✅ 모든 파일 확인됨")

    # 1단계: 키오스크 열기
    print("\n📋 1단계: 키오스크 열기")
    print("키오스크 브라우저를 여는 중...")

    success = run_command('py openKiosk.py --url "http://localhost:3000" --kiosk --zoom 0.65')
    print("⏳ 5초 대기...")
    time.sleep(5)

    # 2단계: UI 좌표 분석
    print("\n📋 2단계: UI 좌표 분석")
    print("카테고리와 버튼의 이름, 위치 인식 중...")

    success = run_command('py ocrFirst.py')
    if not success:
        print("❌ UI 좌표 분석 실패")
        return

    # 카테고리 정보 읽어서 표시
    if os.path.exists("kiosk_ui_coords_easyocr.json"):
        try:
            import json
            with open("kiosk_ui_coords_easyocr.json", 'r', encoding='utf-8') as f:
                coords_data = json.load(f)

            categories = coords_data.get('categories', [])
            for cat in categories:
                cat_name = cat.get('name', 'Unknown')
                print(f"카테고리 '{cat_name}' 찾아냄!")
                time.sleep(0.5)
        except Exception as e:
            print(f"카테고리 정보 읽기 실패: {e}")

    print("⏳ 3초 대기...")
    time.sleep(3)

    # 3단계: 메뉴 캡처
    print("\n📋 3단계: 메뉴 캡처")
    print("화면 캡처를 시작합니다...")

    success = run_command('py kioskMenuCapture.py --coords "kiosk_ui_coords_easyocr.json" --outdir "captures"')
    if not success:
        print("❌ 메뉴 캡처 실패")
        return

    # 캡처된 카테고리 정보 표시
    if os.path.exists("../captures"):
        categories = [d for d in os.listdir("../captures") if os.path.isdir(os.path.join("../captures", d))]
        for cat in categories:
            cat_dir = os.path.join("../captures", cat)
            pages = [f for f in os.listdir(cat_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
            print(f"'{cat}' 카테고리 {len(pages)}페이지 정보 모으는 중...")
            time.sleep(0.3)

    print("⏳ 3초 대기...")
    time.sleep(3)

    # 4단계: 메뉴 분석
    print("\n📋 4단계: 메뉴 분석")
    print("메뉴명과 가격, 위치 정보 모으는 중...")

    success = run_command('py kioskAnalyzeEasyOCR.py --indir "captures" --out "menu_cards.json"')
    if not success:
        print("❌ 메뉴 분석 실패")
        return

    # 분석 결과 개요만 표시 (개별 항목 출력 제거)
    if os.path.exists("menu_cards.json"):
        try:
            import json
            with open("menu_cards.json", 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"분석 결과 로드 완료: {len(data)}개 항목")
        except Exception as e:
            print(f"분석 결과 표시 실패: {e}")

    # 결과 확인
    print("\n📊 결과 확인")
    if os.path.exists("menu_cards.json"):
        try:
            import json
            with open("menu_cards.json", 'r', encoding='utf-8') as f:
                data = json.load(f)

            categories = {}
            for item in data:
                cat = item.get('category', 'Unknown')
                categories[cat] = categories.get(cat, 0) + 1

            print(f"총 메뉴 수: {len(data)}개")
            for cat, count in categories.items():
                print(f"  {cat}: {count}개")

            print("\n🎉 완료!")

        except Exception as e:
            print(f"결과 파일 읽기 오류: {e}")
    else:
        print("❌ 결과 파일이 없습니다")

if __name__ == "__main__":
    main()
