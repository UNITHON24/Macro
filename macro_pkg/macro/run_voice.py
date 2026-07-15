#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
음성인식 키오스크 매크로
실시간 음성 녹음 및 주문 자동 처리
"""

import sys
import os
import traceback

# Windows DPI Awareness 설정 (좌표 오프셋 방지)
if os.name == "nt":
    try:
        import ctypes
        # Per-monitor DPI aware (2)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# 현재 디렉토리를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    try:
        print("🎤 음성인식 키오스크 매크로 시작...")
        print("=" * 50)
        
        # 필요한 모듈 확인
        required_modules = [
            'tkinter', 'pyautogui', 'sounddevice', 'webrtcvad', 
            'websockets', 'requests', 'numpy', 'pygame', 'pydub'
        ]
        
        missing_modules = []
        for module in required_modules:
            try:
                __import__(module)
                print(f"✅ {module}")
            except ImportError:
                missing_modules.append(module)
                print(f"❌ {module} (설치 필요)")
        
        if missing_modules:
            print(f"\n⚠️  다음 모듈을 설치해주세요:")
            print(f"py -m pip install {' '.join(missing_modules)}")
            return 1
        
        # 메뉴 인덱스 파일 확인
        from voice.config import Config
        cfg = Config()
        
        if not os.path.exists(cfg.ui_coords_path):
            print(f"❌ UI 좌표 파일을 찾을 수 없습니다: {cfg.ui_coords_path}")
            return 1
            
        if not os.path.exists(cfg.menu_cards_path):
            print(f"❌ 메뉴 카드 파일을 찾을 수 없습니다: {cfg.menu_cards_path}")
            return 1
        
        print(f"✅ UI 좌표: {cfg.ui_coords_path}")
        print(f"✅ 메뉴 카드: {cfg.menu_cards_path}")
        print(f"✅ WebSocket: {cfg.audio_ws_url}")
        print(f"✅ 주문 API: {cfg.orders_url}")
        print(f"✅ 포인터 동작: {'DRY RUN' if cfg.dry_run else 'LIVE CLICKS ENABLED'}")
        print(
            f"✅ 결제 동작 시뮬레이션: "
            f"{'ENABLED' if cfg.allow_checkout and cfg.dry_run else 'BLOCKED'}"
        )
        
        print("\n🚀 마이크 오버레이 시작...")
        print("💡 마이크 버튼을 클릭하여 녹음을 시작하세요")
        print("💡 드래그하여 위치를 이동할 수 있습니다")
        print("💡 ESC 키로 종료할 수 있습니다")
        
        # 오버레이 실행
        from voice.overlay import MicOverlay
        
        overlay = MicOverlay()
        
        # ESC 키 바인딩
        def on_escape(event):
            if event.keysym == 'Escape':
                print("\n👋 프로그램 종료...")
                overlay.root.quit()
        
        overlay.root.bind('<Key>', on_escape)
        overlay.root.focus_set()
        
        overlay.run()
        
        print("✅ 프로그램 정상 종료")
        return 0
        
    except KeyboardInterrupt:
        print("\n👋 사용자에 의해 중단됨")
        return 0
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        print("\n상세 오류 정보:")
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
