from __future__ import annotations
from typing import Dict, List, Tuple
import time
from .navigator import Navigator

class OrderMacro:
    def __init__(self, nav: Navigator):
        self.nav = nav
        self.execution_history: List[Tuple[str, bool]] = []

    def perform(self, items: List[Dict]) -> Dict[str, any]:
        """
        items 예시:
          [{"name":"화이트 모카","count":1}, {"menu":"레몬에이드","qty":2}]
        
        Returns:
          {"success": True, "results": [{"name": "...", "success": True, "count": 1}, ...]}
        """
        print(f"[MACRO] 주문 처리 시작: {len(items)}개 항목")
        
        results = []
        total_success = 0
        
        for i, item in enumerate(items):
            # 메뉴명과 수량 추출
            # 백엔드(MacroOrderItem) 형태(displayName/menuName, quantity)와
            # 기존 형태(name/menu, count/qty)를 모두 지원
            name = (
                item.get("name")
                or item.get("menu")
                or item.get("item")
                or item.get("displayName")
                or item.get("menuName")
                or ""
            )
            count = (
                item.get("count")
                or item.get("qty")
                or item.get("quantity")
                or 1
            )
            try:
                count = int(count)
            except Exception:
                count = 1
            
            if not name:
                print(f"[MACRO] 항목 {i+1}: 메뉴명 없음 - 건너뜀")
                results.append({"name": f"항목{i+1}", "success": False, "count": 0, "error": "메뉴명 없음"})
                continue
                
            print(f"[MACRO] 항목 {i+1}: '{name}' {count}개 처리 중...")
            
            try:
                # positionTest.py와 동일한 방식으로 메뉴 찾기
                if name not in self.nav.idx.name_to_entry:
                    print(f"[MACRO] '{name}' 메뉴를 찾을 수 없음")
                    results.append({
                        "name": name,
                        "success": False,
                        "count": count,
                        "error": "메뉴를 찾을 수 없음"
                    })
                    self.execution_history.append((name, False))
                    continue
                
                # 각 주문 처리 전 네비게이션 상태 초기화 (중요!)
                print(f"[MACRO] '{name}' 처리 전 네비게이션 상태 초기화")
                self.nav.reset_navigation()
                
                # 매크로 실행 (positionTest.py와 동일한 방식)
                success = self.nav.add_item_like_position_test(str(name), int(count))
                
                if success:
                    total_success += 1
                    print(f"[MACRO] '{name}' 처리 성공")
                else:
                    print(f"[MACRO] '{name}' 처리 실패")
                    
                results.append({
                    "name": name,
                    "success": success,
                    "count": count,
                    "error": None if success else "매크로 실행 실패"
                })
                
                # 실행 기록 저장
                self.execution_history.append((name, success))
                
            except Exception as e:
                print(f"[MACRO] '{name}' 처리 중 오류: {e}")
                results.append({
                    "name": name,
                    "success": False,
                    "count": count,
                    "error": str(e)
                })
                self.execution_history.append((name, False))
        
        # 모든 담기 완료 후 결제하기 버튼 클릭
        payment_clicked = False
        try:
            pay_xy = (989, 1880)
            print(f"[PAY] 결제하기 버튼 클릭 시도 @ {pay_xy}")
            self.nav.click(pay_xy)
            time.sleep(self.nav.cfg.item_click_delay)
            payment_clicked = True
            print("[PAY] 결제하기 클릭 완료")
        except Exception as e:
            print(f"[PAY] 결제 클릭 실패: {e}")

        # 최종 네비게이션 상태 초기화
        self.nav.reset_navigation()
        
        summary = {
            "success": total_success == len(items),
            "total_items": len(items),
            "successful_items": total_success,
            "failed_items": len(items) - total_success,
            "results": results,
            "payment_clicked": payment_clicked
        }
        
        print(f"[MACRO] 주문 처리 완료: {total_success}/{len(items)} 성공")
        return summary

    def get_execution_history(self) -> List[Tuple[str, bool]]:
        """매크로 실행 기록 반환"""
        return self.execution_history.copy()

    def clear_history(self):
        """실행 기록 초기화"""
        self.execution_history.clear()
        print("[MACRO] 실행 기록 초기화")
