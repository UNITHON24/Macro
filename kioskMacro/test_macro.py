#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
매크로 기능 테스트 스크립트
실제 키오스크 없이도 매크로 로직을 테스트할 수 있습니다.
"""

import sys
import os
import json

# 현재 디렉토리를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_menu_index():
    """메뉴 인덱스 로딩 테스트"""
    print("🔍 메뉴 인덱스 테스트...")
    
    try:
        from voice.config import Config
        from voice.index_loader import MenuIndex
        
        cfg = Config()
        print(f"설정 파일 경로:")
        print(f"  UI 좌표: {cfg.ui_coords_path}")
        print(f"  메뉴 카드: {cfg.menu_cards_path}")
        
        # 파일 존재 확인
        if not os.path.exists(cfg.ui_coords_path):
            print(f"❌ UI 좌표 파일 없음: {cfg.ui_coords_path}")
            return False
            
        if not os.path.exists(cfg.menu_cards_path):
            print(f"❌ 메뉴 카드 파일 없음: {cfg.menu_cards_path}")
            return False
        
        # 인덱스 로딩
        index = MenuIndex(cfg.ui_coords_path, cfg.menu_cards_path)
        
        print(f"✅ 카테고리 수: {len(index.category_centers)}")
        print(f"✅ 메뉴 수: {len(index.name_to_entry)}")
        print(f"✅ 네비게이션 버튼:")
        print(f"    이전: {index.prev_xy}")
        print(f"    다음: {index.next_xy}")
        
        # 샘플 메뉴 검색 테스트
        test_names = ["화이트 모카", "레몬에이드", "아메리카노"]
        for name in test_names:
            result = index.find_menu_best(name)
            if result:
                best_name, cat, page, xy = result
                print(f"✅ '{name}' → '{best_name}' ({cat} p{page} @ {xy})")
            else:
                print(f"❌ '{name}' 매칭 실패")
        
        return True
        
    except Exception as e:
        print(f"❌ 메뉴 인덱스 테스트 실패: {e}")
        return False

def test_navigator():
    """네비게이터 테스트 (DRY RUN 모드)"""
    print("\n🧭 네비게이터 테스트 (DRY RUN)...")
    
    try:
        from voice.config import Config
        from voice.index_loader import MenuIndex
        from voice.navigator import Navigator
        
        # DRY RUN 모드로 설정
        os.environ["KIOSK_DRY_RUN"] = "1"
        
        cfg = Config()
        index = MenuIndex(cfg.ui_coords_path, cfg.menu_cards_path)
        nav = Navigator(index, cfg)
        
        # 샘플 주문 테스트
        test_orders = [
            {"name": "화이트 모카", "count": 1},
            {"name": "레몬에이드", "count": 2}
        ]
        
        for order in test_orders:
            name = order["name"]
            count = order["count"]
            print(f"\n📋 '{name}' {count}개 처리 테스트:")
            
            result = index.find_menu_best(name)
            if result:
                best_name, cat, page, xy = result
                print(f"  매칭: '{name}' → '{best_name}'")
                print(f"  위치: {cat} 카테고리, {page}페이지, 좌표 {xy}")
                
                # 네비게이션 시뮬레이션
                success = nav.add_item(name, count)
                print(f"  결과: {'성공' if success else '실패'}")
            else:
                print(f"  ❌ 메뉴 매칭 실패")
        
        return True
        
    except Exception as e:
        print(f"❌ 네비게이터 테스트 실패: {e}")
        return False

def test_macro():
    """매크로 실행 테스트"""
    print("\n🤖 매크로 실행 테스트...")
    
    try:
        from voice.config import Config
        from voice.index_loader import MenuIndex
        from voice.navigator import Navigator
        from voice.macro import OrderMacro
        
        # DRY RUN 모드로 설정
        os.environ["KIOSK_DRY_RUN"] = "1"
        
        cfg = Config()
        index = MenuIndex(cfg.ui_coords_path, cfg.menu_cards_path)
        nav = Navigator(index, cfg)
        macro = OrderMacro(nav)
        
        # 복합 주문 테스트
        test_items = [
            {"name": "화이트 모카", "count": 1},
            {"name": "레몬에이드", "count": 2},
            {"name": "아메리카노", "count": 1}
        ]
        
        print(f"📋 주문 항목: {len(test_items)}개")
        for item in test_items:
            print(f"  - {item['name']} {item['count']}개")
        
        # 매크로 실행
        result = macro.perform(test_items)
        
        print(f"\n📊 실행 결과:")
        print(f"  전체 성공: {'예' if result['success'] else '아니오'}")
        print(f"  총 항목: {result['total_items']}")
        print(f"  성공: {result['successful_items']}")
        print(f"  실패: {result['failed_items']}")
        
        # 상세 결과
        for item_result in result['results']:
            status = "✅" if item_result['success'] else "❌"
            print(f"  {status} {item_result['name']} {item_result['count']}개")
            if item_result['error']:
                print(f"      오류: {item_result['error']}")
        
        return True
        
    except Exception as e:
        print(f"❌ 매크로 테스트 실패: {e}")
        return False

def main():
    """메인 테스트 함수"""
    print("🧪 음성인식 키오스크 매크로 테스트")
    print("=" * 50)
    
    # 환경 변수 설정
    os.environ["KIOSK_DRY_RUN"] = "1"
    
    tests = [
        ("메뉴 인덱스", test_menu_index),
        ("네비게이터", test_navigator),
        ("매크로 실행", test_macro)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        try:
            if test_func():
                passed += 1
                print(f"✅ {test_name} 테스트 통과")
            else:
                print(f"❌ {test_name} 테스트 실패")
        except Exception as e:
            print(f"❌ {test_name} 테스트 오류: {e}")
    
    print(f"\n{'='*50}")
    print(f"📊 테스트 결과: {passed}/{total} 통과")
    
    if passed == total:
        print("🎉 모든 테스트 통과!")
        return 0
    else:
        print("⚠️  일부 테스트 실패")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
