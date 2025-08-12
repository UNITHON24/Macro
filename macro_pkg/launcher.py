#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
launcher.py
- 전체 실행 순서 자동화:
  1) settingPack/firstSetting.py 실행(동기)
  2) Backend-master Gradle 서버 부팅(백그라운드) 및 8080 대기
  3) kioskMacro/kioskMacro/kioskMacro/ordersHub.py 실행(백그라운드) 및 9999 대기
  4) kioskMacro/kioskMacro/kioskMacro/run_voice.py 실행(포그라운드)

사용:
  py launcher.py
"""

import os
import sys
import time
import subprocess
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYROOT = ROOT / "kioskMacro"
# Backend 경로: 기본은 프로젝트 루트의 "Backend-master".
# 환경변수 KIOSK_BACKEND_DIR로 상대/절대 지정 가능.
_backend_env = os.environ.get("KIOSK_BACKEND_DIR")
if _backend_env:
    _p = Path(_backend_env)
    BACKEND = (_p if _p.is_absolute() else (ROOT / _p)).resolve()
else:
    BACKEND = (ROOT / "Backend-master").resolve()

# MySQL auto-start (optional):
# - KIOSK_MYSQL_BIN: mysqld.exe 경로나 디렉터리 (예: C:\\Program Files\\MySQL\\MySQL Server 8.4\\bin)
# - KIOSK_MYSQL_DATADIR: 데이터 디렉터리 (예: C:\\Users\\<user>\\mysql-data)
MYSQL_BIN_ENV = os.environ.get("KIOSK_MYSQL_BIN", "").strip()
MYSQL_DATADIR = os.environ.get("KIOSK_MYSQL_DATADIR", "").strip()
ORDERS = PYROOT / "kioskMacro" / "ordersHub.py"
RUN_VOICE = PYROOT / "kioskMacro" / "run_voice.py"
FIRST = PYROOT / "settingPack" / "firstSetting.py"


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
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)


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
    # 1) firstSetting.py 실행
    if not FIRST.exists():
        print(f"[ERR] not found: {FIRST}")
        return 1
    code = run_sync([sys.executable, str(FIRST)], cwd=FIRST.parent)
    if code != 0:
        print(f"[ERR] firstSetting.py 실패 (코드 {code})")
        return code

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
