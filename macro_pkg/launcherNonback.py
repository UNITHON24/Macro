#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
launcherNonback.py
- 백엔드 서버 기동 없이 다음 순서만 자동화:
  1) 기존 메뉴 좌표·인덱스 확인(보정은 KIOSK_RUN_CALIBRATION=1일 때만 실행)
  2) macro/ordersHub.py 실행(백그라운드) 및 9999 대기
  3) macro/run_voice.py 실행(포그라운드)

사용:
  py launcherNonback.py
"""

import os
import sys
import time
import subprocess
import socket
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
MACRO_ROOT = PACKAGE_ROOT / "macro"
ORDERS = MACRO_ROOT / "ordersHub.py"
RUN_VOICE = MACRO_ROOT / "run_voice.py"
FIRST = PACKAGE_ROOT / "settingPack" / "firstSetting.py"
sys.path.insert(0, str(MACRO_ROOT))

from voice.config import Config


def wait_port(host: str, port: int, timeout_sec: int = 60) -> bool:
    """TCP 포트가 열릴 때까지 대기"""
    end = time.time() + timeout_sec
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def run_sync(cmd: list[str], cwd: Path | None = None) -> int:
    print(f"[RUN] {' '.join(cmd)} | cwd={cwd or os.getcwd()}")
    return subprocess.call(cmd, cwd=str(cwd) if cwd else None)


def run_bg(cmd: list[str], cwd: Path | None = None) -> subprocess.Popen:
    print(f"[BG ] {' '.join(cmd)} | cwd={cwd or os.getcwd()}")
    return subprocess.Popen(cmd, cwd=str(cwd) if cwd else None,
                            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)


def calibration_requested() -> bool:
    return os.environ.get("KIOSK_RUN_CALIBRATION", "").strip().casefold() in {
        "1", "true", "yes", "on"
    }


def prepare_client_files() -> bool:
    if calibration_requested():
        print("[CAL] 명시적으로 요청된 키오스크 좌표 보정을 시작합니다.")
        code = run_sync([sys.executable, str(FIRST)], cwd=FIRST.parent)
        if code != 0:
            print(f"[ERR] firstSetting.py 실패 (코드 {code})")
            return False
    else:
        print("[SAFE] 좌표 보정 건너뜀 (KIOSK_RUN_CALIBRATION 미설정)")

    config = Config()
    if len(config.orders_token) < 32:
        print("[ERR] KIOSK_ORDER_TOKEN with at least 32 characters is required")
        return False
    required_paths = [
        Path(config.ui_coords_path),
        Path(config.menu_cards_path),
        Path(config.profile_path),
    ]
    missing_paths = [path for path in required_paths if not path.is_file()]
    if missing_paths:
        for path in missing_paths:
            print(f"[ERR] required client data not found: {path}")
        print("[HINT] 테스트 키오스크에서 KIOSK_RUN_CALIBRATION=1로 다시 실행하세요.")
        return False
    return True


def main() -> int:
    # 1) 기존 좌표 확인. 실제 포인터를 쓰는 보정은 명시적 opt-in만 허용.
    if not prepare_client_files():
        return 1

    # 2) ordersHub.py 백그라운드 실행
    if not ORDERS.exists():
        print(f"[ERR] not found: {ORDERS}")
        return 1
    if wait_port("127.0.0.1", 9999, 1):
        print("[ERR] 9999 포트가 이미 사용 중입니다. 기존 ordersHub를 종료하세요.")
        return 3
    orders_process = run_bg([sys.executable, str(ORDERS)], cwd=ORDERS.parent)
    print("[WAIT] http://localhost:9999 준비 대기...")
    if not wait_port("127.0.0.1", 9999, 60):
        print("[ERR] 9999 포트 준비 실패")
        return 3
    if orders_process.poll() is not None:
        print("[ERR] 새 ordersHub 프로세스가 시작 직후 종료됐습니다.")
        return 3
    print("[OK ] 9999 준비 완료")

    # 3) run_voice.py 포그라운드 실행
    if not RUN_VOICE.exists():
        print(f"[ERR] not found: {RUN_VOICE}")
        return 1
    return run_sync([sys.executable, str(RUN_VOICE)], cwd=RUN_VOICE.parent)


if __name__ == "__main__":
    sys.exit(main())
