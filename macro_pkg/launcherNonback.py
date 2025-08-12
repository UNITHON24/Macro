#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
launcherNonback.py
- 백엔드 서버 기동 없이 다음 순서만 자동화:
  1) settingPack/firstSetting.py 실행(동기)
  2) kioskMacro/kioskMacro/kioskMacro/ordersHub.py 실행(백그라운드) 및 9999 대기
  3) kioskMacro/kioskMacro/kioskMacro/run_voice.py 실행(포그라운드)

사용:
  py launcherNonback.py
"""

import os
import sys
import time
import subprocess
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYROOT = ROOT / "kioskMacro"
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


def main() -> int:
    # 1) firstSetting.py 실행
    if not FIRST.exists():
        print(f"[ERR] not found: {FIRST}")
        return 1
    code = run_sync([sys.executable, str(FIRST)], cwd=FIRST.parent)
    if code != 0:
        print(f"[ERR] firstSetting.py 실패 (코드 {code})")
        return code

    # 2) ordersHub.py 백그라운드 실행
    if not ORDERS.exists():
        print(f"[ERR] not found: {ORDERS}")
        return 1
    run_bg([sys.executable, str(ORDERS)], cwd=ORDERS.parent)
    print("[WAIT] http://localhost:9999 준비 대기...")
    if not wait_port("127.0.0.1", 9999, 60):
        print("[ERR] 9999 포트 준비 실패")
        return 3
    print("[OK ] 9999 준비 완료")

    # 3) run_voice.py 포그라운드 실행
    if not RUN_VOICE.exists():
        print(f"[ERR] not found: {RUN_VOICE}")
        return 1
    return run_sync([sys.executable, str(RUN_VOICE)], cwd=RUN_VOICE.parent)


if __name__ == "__main__":
    sys.exit(main())
