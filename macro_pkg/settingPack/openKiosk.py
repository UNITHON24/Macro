# open_kiosk_force_fullscreen_zoom.py
import os, subprocess, tempfile, argparse

URL = "https://frontend-phi-tan.vercel.app/"

CANDIDATES = [
    os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "Microsoft", "Edge", "Application", "msedge.exe"),
    os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), "Microsoft", "Edge", "Application", "msedge.exe"),
    os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "Google", "Chrome", "Application", "chrome.exe"),
    os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), "Google", "Chrome", "Application", "chrome.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Users\%USERNAME%\AppData\Local"), "Google", "Chrome", "Application", "chrome.exe"),
]

def pick_browser():
    for p in CANDIDATES:
        if os.path.exists(p):
            return p
    raise RuntimeError("Chrome/Edge 실행 파일을 찾지 못했습니다. 설치 경로를 CANDIDATES에 추가하세요.")

def open_fullscreen(url=URL, kiosk=True, zoom=0.65, window_size=None):
    exe = pick_browser()
    name = os.path.basename(exe).lower()

    # 새 프로필(캐시)로 실행: 플래그가 100% 적용되도록
    temp_profile = tempfile.mkdtemp(prefix="kiosk_profile_")

    base_flags = [
        f"--user-data-dir={temp_profile}",
        "--no-first-run",
        "--new-window",
        "--disable-features=TranslateUI",
        "--high-dpi-support=1",
        f"--force-device-scale-factor={zoom}",   # ★ 렌더링 배율 강제
        "--disable-pinch",                       # 터치/휠 확대 축소 방지(선택)
    ]
    
    # 기본적으로 1080x1920 창 크기 설정 (세로 모드)
    if not kiosk:
        base_flags.append("--window-size=1080,1920")
        base_flags.append("--window-position=0,0")
    
    # 사용자가 지정한 창 크기가 있으면 덮어쓰기
    if not kiosk and window_size:
        width, height = window_size
        base_flags = [flag for flag in base_flags if not flag.startswith("--window-size=")]
        base_flags.append(f"--window-size={width},{height}")

    if "msedge" in name:
        flags = base_flags + (["--kiosk", url, "--edge-kiosk-type=fullscreen"] if kiosk
                              else ["--start-fullscreen", url])
    else:  # chrome
        flags = base_flags + (["--kiosk", url] if kiosk else ["--start-fullscreen", url])

    subprocess.Popen([exe] + flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"브라우저를 전체화면으로 열었습니다. 배율={int(zoom*100)}%. 종료: Alt+F4")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL)
    ap.add_argument("--kiosk", action="store_true", help="탭/주소창 숨기는 진짜 키오스크 모드")
    ap.add_argument("--zoom", type=float, default=0.65, help="렌더링 배율 (예: 0.75 = 75%)")
    ap.add_argument("--window-size", nargs=2, type=int, metavar=("WIDTH", "HEIGHT"), 
                   help="창 크기 설정 (예: 1920 1080)")
    args = ap.parse_args()
    
    window_size = tuple(args.window_size) if args.window_size else None
    open_fullscreen(args.url, kiosk=args.kiosk, zoom=args.zoom, window_size=window_size)
    
    # 기본 실행 시 안내 메시지
    if not args.kiosk and not args.window_size:
        print("브라우저를 1080x1920 크기로 열었습니다. 전체화면: F11")
