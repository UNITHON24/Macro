#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
launcher.py
- 전체 실행 순서 자동화:
  1) 기존 메뉴 좌표·인덱스 확인(보정은 KIOSK_RUN_CALIBRATION=1일 때만 실행)
  2) Backend-master Gradle 서버 부팅(백그라운드) 및 8080 대기
  3) macro/ordersHub.py 실행(백그라운드) 및 9999 대기
  4) macro/run_voice.py 실행(포그라운드)

사용:
  py launcher.py
"""

import os
import sys
import time
import subprocess
import socket
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PACKAGE_ROOT.parent
MACRO_ROOT = PACKAGE_ROOT / "macro"
# Backend 경로: 기본은 프로젝트 루트의 "Backend-master".
# 환경변수 KIOSK_BACKEND_DIR로 상대/절대 지정 가능.
_backend_env = os.environ.get("KIOSK_BACKEND_DIR")
if _backend_env:
    _p = Path(_backend_env)
    BACKEND = (_p if _p.is_absolute() else (REPOSITORY_ROOT / _p)).resolve()
else:
    BACKEND = (REPOSITORY_ROOT / "Backend-master").resolve()

# MySQL auto-start (optional):
# - KIOSK_MYSQL_BIN: mysqld.exe 경로나 디렉터리 (예: C:\\Program Files\\MySQL\\MySQL Server 8.4\\bin)
# - KIOSK_MYSQL_DATADIR: 데이터 디렉터리 (예: C:\\Users\\<user>\\mysql-data)
MYSQL_BIN_ENV = os.environ.get("KIOSK_MYSQL_BIN", "").strip()
MYSQL_DATADIR = os.environ.get("KIOSK_MYSQL_DATADIR", "").strip()
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
    required_paths = [Path(config.ui_coords_path), Path(config.menu_cards_path)]
    missing_paths = [path for path in required_paths if not path.is_file()]
    if missing_paths:
        for path in missing_paths:
            print(f"[ERR] required client data not found: {path}")
        print("[HINT] 테스트 키오스크에서 KIOSK_RUN_CALIBRATION=1로 다시 실행하세요.")
        return False
    return True


def maybe_start_mysql() -> bool:
    """3306 포트가 닫혀 있으면 mysqld를 기동. 성공 시 True, 스킵 또는 실패 시 False."""
    # 이미 떠 있으면 OK
    if wait_port("127.0.0.1", 3306, 1):
        print("[OK ] MySQL(3306) 이미 실행 중")
        return True

    # 환경설정 확인
    if not MYSQL_BIN_ENV or not MYSQL_DATADIR:
        print("[SKIP] MySQL 자동기동 비활성화 (KIOSK_MYSQL_BIN/KIOSK_MYSQL_DATADIR 미설정)")
        return False

    # 실행 경로 결정
    bin_path = Path(MYSQL_BIN_ENV)
    mysqld = bin_path if bin_path.suffix.lower() == ".exe" else (bin_path / ("mysqld.exe" if os.name == "nt" else "mysqld"))
    if not mysqld.exists():
        print(f"[ERR] mysqld 경로 없음: {mysqld}")
        return False

    # 기동
    args = [str(mysqld), f"--datadir={MYSQL_DATADIR}"]
    if os.name == "nt":
        args.append("--console")
    run_bg(args, cwd=mysqld.parent)
    print("[WAIT] MySQL 3306 대기...")
    if not wait_port("127.0.0.1", 3306, 60):
        print("[ERR] MySQL 3306 포트 준비 실패")
        return False
    print("[OK ] MySQL 준비 완료")
    return True


def main() -> int:
    # 1) 기존 좌표 확인. 실제 포인터를 쓰는 보정은 명시적 opt-in만 허용.
    if not prepare_client_files():
        return 1

    # 2) MySQL 준비 (옵션)
    mysql_ready = maybe_start_mysql()

    # 3) 백엔드 bootRun 백그라운드 실행
    gradlew = BACKEND / "gradlew.bat"
    if not gradlew.exists():
        print(f"[ERR] not found: {gradlew}")
        return 1
    run_bg([str(gradlew), "bootRun"], cwd=BACKEND)
    print("[WAIT] http://localhost:8080 준비 대기...")
    if not wait_port("127.0.0.1", 8080, 120):
        print("[ERR] 8080 포트 준비 실패")
        return 2
    print("[OK ] 8080 준비 완료")

    # 4) ordersHub.py 백그라운드 실행
    if not ORDERS.exists():
        print(f"[ERR] not found: {ORDERS}")
        return 1
    run_bg([sys.executable, str(ORDERS)], cwd=ORDERS.parent)
    print("[WAIT] http://localhost:9999 준비 대기...")
    if not wait_port("127.0.0.1", 9999, 60):
        print("[ERR] 9999 포트 준비 실패")
        return 3
    print("[OK ] 9999 준비 완료")

    # 5) run_voice.py 포그라운드 실행
    if not RUN_VOICE.exists():
        print(f"[ERR] not found: {RUN_VOICE}")
        return 1
    return run_sync([sys.executable, str(RUN_VOICE)], cwd=RUN_VOICE.parent)


if __name__ == "__main__":
    sys.exit(main())
