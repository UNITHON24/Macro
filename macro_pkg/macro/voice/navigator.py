from __future__ import annotations
import time
import pyautogui
from typing import Tuple, Optional
from .index_loader import MenuIndex
from .config import Config

# 안전 설정: 실수로 모서리 이동 시 중단 방지, 전역 대기 제거로 클릭 응답성 향상
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

class Navigator:
    def __init__(self, index: MenuIndex, cfg: Config):
        self.idx = index
        self.cfg = cfg
        self.current_category = None
        self.current_page = 1

    def click(self, xy: Tuple[int, int]):
        x, y = xy
        if self.cfg.dry_run:
            print(f"[DRY] click({x},{y})")
        else:
            try:
                # 현재 마우스 위치 확인
                current_pos = pyautogui.position()
                print(f"[CLICK] 현재 마우스 위치: {current_pos}")
                
                # 더 확실한 클릭: moveTo + mouseDown/Up, 약간의 dwell
                print(f"[CLICK] 마우스 이동 중... ({x},{y})")
                pyautogui.moveTo(x, y, duration=0.1)  # 부드러운 이동으로 변경
                
                # 이동 완료 후 위치 확인
                moved_pos = pyautogui.position()
                print(f"[CLICK] 이동 후 마우스 위치: {moved_pos}")
                
                # 위치가 정확한지 확인
                if abs(moved_pos.x - x) > 2 or abs(moved_pos.y - y) > 2:
                    print(f"[WARN] 마우스 위치가 목표와 다름: 목표({x},{y}) vs 실제({moved_pos.x},{moved_pos.y})")
                    # 다시 정확한 위치로 이동
                    pyautogui.moveTo(x, y, duration=0.05)
                    moved_pos = pyautogui.position()
                    print(f"[CLICK] 재이동 후 위치: {moved_pos}")
                
                print(f"[CLICK] 마우스 다운... ({x},{y})")
                pyautogui.mouseDown(x, y)
                time.sleep(0.05)  # 다운 시간 증가
                
                print(f"[CLICK] 마우스 업... ({x},{y})")
                pyautogui.mouseUp(x, y)
                
                # 최종 마우스 위치 확인
                final_pos = pyautogui.position()
                print(f"[CLICK] 클릭 완료: 목표({x},{y}) → 최종 마우스 위치({final_pos.x},{final_pos.y})")
                
                # 클릭 후 잠시 대기
                time.sleep(0.1)
                
            except Exception as e:
                print(f"[ERR] 클릭 실패 ({x},{y}): {e}")

    def go_category(self, cat: str) -> bool:
        if cat not in self.idx.category_centers:
            print(f"[WARN] 카테고리 좌표 없음: {cat}")
            return False
            
        xy = self.idx.category_centers[cat]
        print(f"[NAV] 카테고리 '{cat}' → {xy}")
        
        try:
            print(f"[NAV] 카테고리 '{cat}' 클릭 시작...")
            self.click(xy)
            time.sleep(self.cfg.cat_click_delay)
            self.current_category = cat
            self.current_page = 1  # 카테고리 선택 시 1페이지로 이동
            print(f"[NAV] 카테고리 '{cat}' 선택 완료")
            return True
        except Exception as e:
            print(f"[ERR] 카테고리 선택 실패: {e}")
            return False

    def go_page_from_one(self, target_page: int) -> bool:
        if target_page <= 1: 
            self.current_page = 1
            print(f"[NAV] 이미 1페이지에 있음")
            return True
            
        if self.current_page == target_page:
            print(f"[NAV] 이미 {target_page}페이지에 있음")
            return True
            
        print(f"[NAV] 1페이지에서 {target_page}페이지로 이동")
        
        try:
            for page in range(1, target_page):
                print(f"[NAV] 다음 페이지 클릭 → {self.idx.next_xy}")
                self.click(self.idx.next_xy)
                time.sleep(self.cfg.page_click_delay)
                self.current_page = page + 1
                print(f"[NAV] {page + 1}페이지로 이동 완료")
                
            print(f"[NAV] {target_page}페이지 도달 완료")
            return True
            
        except Exception as e:
            print(f"[ERR] 페이지 이동 실패: {e}")
            return False

    def add_item_direct(self, name: str, count: int = 1) -> bool:
        """positionTest.py와 동일한 방식으로 메뉴를 찾고 클릭"""
        print(f"[MACRO] '{name}' {count}개 담기 시작 (직접 방식)")
        
        # positionTest.py와 동일하게 name_to_entry에서 직접 찾기
        if name not in self.idx.name_to_entry:
            print(f"[ERR] 메뉴를 찾을 수 없음: '{name}'")
            return False
            
        cat, page, xy = self.idx.name_to_entry[name]
        print(f"[MATCH] '{name}' → '{name}' / {cat} p{page} @ {xy}")
        print(f"[DEBUG] 카테고리: {cat}, 페이지: {page}, 좌표: {xy}")
        
        # 원본 좌표 보존 (중요!)
        original_xy = xy
        print(f"[DEBUG] 원본 좌표 보존: {original_xy}")
        
        # 안전한 시작을 위해 마우스를 화면 중앙으로 이동
        screen_width, screen_height = pyautogui.size()
        safe_x, safe_y = screen_width // 2, screen_height // 2
        print(f"[SAFE] 안전한 위치로 이동: ({safe_x}, {safe_y})")
        pyautogui.moveTo(safe_x, safe_y, duration=0.1)
        time.sleep(0.2)
        
        # positionTest.py와 동일한 순서로 실행 (상태 업데이트 없음)
        
        # 1. 카테고리 클릭 (상태 변경 없음)
        print(f"[MACRO] 카테고리 '{cat}' 클릭 시작...")
        if cat not in self.idx.category_centers:
            print(f"[ERR] 카테고리 좌표 없음: {cat}")
            return False
        cat_xy = self.idx.category_centers[cat]
        print(f"[MACRO] 카테고리 좌표: {cat_xy}")
        self.click(cat_xy)
        time.sleep(self.cfg.cat_click_delay)
        print(f"[MACRO] 카테고리 '{cat}' 클릭 완료")
            
        # 2. 페이지 클릭 (상태 변경 없음)
        print(f"[MACRO] 페이지 {page}로 이동 시작...")
        if page > 1:
            for p in range(1, page):
                print(f"[MACRO] 다음 페이지 클릭 → {self.idx.next_xy}")
                self.click(self.idx.next_xy)
                time.sleep(self.cfg.page_click_delay)
                print(f"[MACRO] {p + 1}페이지로 이동 완료")
        else:
            print(f"[MACRO] 이미 1페이지에 있음")
        print(f"[MACRO] 페이지 {page} 이동 완료")
            
        # 3. 메뉴 클릭 (원본 좌표 사용 - positionTest.py와 동일)
        success_count = 0
        for i in range(max(1, int(count))):
            try:
                print(f"[CLICK] '{name}' 담기 @ 원본좌표 {original_xy} ({i+1}/{count})")
                # 원본 좌표를 그대로 사용 (좌표 변환 없음)
                self.click(original_xy)
                time.sleep(self.cfg.item_click_delay)
                success_count += 1
                print(f"[MACRO] '{name}' {i+1}개 담기 완료")
            except Exception as e:
                print(f"[ERR] 메뉴 클릭 실패: {e}")
                
        print(f"[MACRO] '{name}' {success_count}/{count}개 담기 완료")
        return success_count > 0

    def add_item(self, name: str, count: int = 1) -> bool:
        print(f"[MACRO] '{name}' {count}개 담기 시작")
        
        # 메뉴 검색
        result = self.idx.find_menu_best(name)
        if not result:
            print(f"[ERR] 메뉴 매칭 실패: '{name}'")
            return False
            
        best_name, cat, page, xy = result
        print(f"[MATCH] '{name}' → '{best_name}' / {cat} p{page} @ {xy}")
        
        # 카테고리 이동
        if not self.go_category(cat):
            return False
            
        # 페이지 이동
        if not self.go_page_from_one(page):
            return False
            
        # 메뉴 클릭
        success_count = 0
        for i in range(max(1, int(count))):
            try:
                print(f"[CLICK] '{best_name}' 담기 @ {xy} ({i+1}/{count})")
                self.click(xy)
                time.sleep(self.cfg.item_click_delay)
                success_count += 1
            except Exception as e:
                print(f"[ERR] 메뉴 클릭 실패: {e}")
                
        print(f"[MACRO] '{best_name}' {success_count}/{count}개 담기 완료")
        return success_count > 0

    def add_item_like_position_test(self, name: str, count: int = 1) -> bool:
        """positionTest.py와 완전히 같은 순서/방식으로: go_category -> go_page_from_one -> click(center)."""
        if name not in self.idx.name_to_entry:
            print(f"[ERR] 메뉴를 찾을 수 없음: '{name}'")
            return False
        cat, page, xy = self.idx.name_to_entry[name]
        print(f"[MATCH] '{name}' / {cat} p{page} @ {xy} (positionTest 방식)")
        if not self.go_category(cat):
            return False
        if not self.go_page_from_one(page):
            return False
        success_count = 0
        for i in range(max(1, int(count))):
            self.click(xy)
            time.sleep(self.cfg.item_click_delay)
            success_count += 1
        return success_count > 0

    def reset_navigation(self):
        """네비게이션 상태 초기화"""
        self.current_category = None
        self.current_page = 1
        print("[NAV] 네비게이션 상태 초기화")
