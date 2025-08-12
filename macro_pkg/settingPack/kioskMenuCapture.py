# kioskMenuCapture.py
# 좌표 JSON을 읽어 카테고리/페이지를 빠르게 넘기며
# 메뉴 영역만 스크린샷 저장(분석 없음).
# - 버튼 클릭 후 1초 대기
# - 저장 실패 시 imencode로 강제 저장(fallback)
# - 자세한 로그 출력(작업 폴더/경로/해시/이미지 크기)

import os, re, json, time, hashlib, argparse, sys
import numpy as np
import cv2
from mss import mss
import pygetwindow as gw
import pyautogui as pag

# ====== 기준 해상도 & 최신 메뉴 영역 ======
BASE_W, BASE_H = 1080, 1920  # 세로 모드 해상도 (키오스크용)
# 최신 UI: Point(x=8,y=169) ~ Point(x=735,y=1585)
BASE_MENU = (8, 169, 735, 1585)
MENU_MARGIN = (6, 6)

# ====== 캡처/내비 설정 ======
PAUSE = 0.05
AFTER_CATEGORY_WAIT = 1.00     # 카테고리 클릭 후 1초
AFTER_PAGE_CLICK_WAIT = 1.00   # 이전/다음 클릭 후 1초
POLL_TIMEOUT = 2.0             # 화면 변경 대기 최대 시간(초)
POLL_INTERVAL = 0.05           # 화면 변경 폴링 간격(초)
MAX_PREV_TO_FIRST = 5
MAX_PAGES_PER_CAT = 60

pag.FAILSAFE = False
pag.PAUSE = 0.02

# ---------- 유틸 ----------
def ensure_dir(p):
    os.makedirs(p, exist_ok=True)

def save_image(path, img):
    """cv2.imwrite 실패 시 imencode→바이트로 강제 저장 + 자세한 로그"""
    try:
        ensure_dir(os.path.dirname(path))
    except Exception as e:
        print(f"[ERROR] 디렉터리 생성 실패: {os.path.dirname(path)} -> {e}")
        return False

    abspath = os.path.abspath(path)
    try:
        ok = cv2.imwrite(abspath, img)
        if ok:
            print(f"[SAVE] {abspath}  shape={img.shape} dtype={img.dtype}")
            return True
        else:
            print(f"[WARN] cv2.imwrite 실패: {abspath}. imencode로 재시도...")
    except Exception as e:
        print(f"[WARN] cv2.imwrite 예외: {abspath} -> {e}. imencode로 재시도...")

    # Fallback: imencode → 바이너리 저장 (유니코드/권한 이슈 우회 시도)
    root, ext = os.path.splitext(abspath)
    ext = (ext or ".png").lower()
    if ext not in [".png", ".jpg", ".jpeg", ".bmp", ".tiff"]:
        ext = ".png"
        abspath = root + ext
    encode_ext = ".jpg" if ext in [".jpg", ".jpeg"] else ".png"

    ok, buf = cv2.imencode(encode_ext, img)
    if not ok:
        print(f"[ERROR] cv2.imencode 실패: {encode_ext}, 경로={abspath}")
        return False
    try:
        with open(abspath, "wb") as f:
            f.write(buf.tobytes())
        print(f"[SAVE:FALLBACK] {abspath}  shape={img.shape} dtype={img.dtype}")
        return True
    except Exception as e:
        print(f"[ERROR] 파일 기록 실패: {abspath} -> {e}")
        return False

def primary_monitor_rect():
    with mss() as sct:
        mon = sct.monitors[1]
        return (mon["left"], mon["top"], mon["left"]+mon["width"], mon["top"]+mon["height"])

def get_browser_window_rect():
    # 활성 창 우선
    try:
        w = gw.getActiveWindow()
        if w and w.width > 0 and w.height > 0:
            return (w.left, w.top, w.right, w.bottom)
    except Exception:
        pass
    # 제목 키워드 보조
    for kw in ["localhost", "edge", "chrome", "react"]:
        try:
            wins = gw.getWindowsWithTitle(kw)
            if wins:
                w = wins[0]
                return (w.left, w.top, w.right, w.bottom)
        except Exception:
            pass
    # 실패 시: 주 모니터 전체
    return primary_monitor_rect()

def clamp_rect_to_screen(x1,y1,x2,y2):
    sx1, sy1, sx2, sy2 = primary_monitor_rect()
    x1 = max(sx1, x1); y1 = max(sy1, y1)
    x2 = min(sx2, x2); y2 = min(sy2, y2)
    if x2 <= x1: x2 = x1 + 1
    if y2 <= y1: y2 = y1 + 1
    return (x1,y1,x2,y2)

def scale_region(base_rect, win_rect, margin=(0,0)):
    bx1,by1,bx2,by2 = base_rect
    wx1,wy1,wx2,wy2 = win_rect
    ww, wh = (wx2-wx1), (wy2-wy1)
    sx, sy = ww/BASE_W, wh/BASE_H
    x1 = int(wx1 + bx1*sx) - margin[0]
    y1 = int(wy1 + by1*sy) - margin[1]
    x2 = int(wx1 + bx2*sx) + margin[0]
    y2 = int(wy1 + by2*sy) + margin[1]
    return clamp_rect_to_screen(x1,y1,x2,y2)

def grab_region_abs(x1,y1,x2,y2):
    with mss() as sct:
        mon = {"left": x1, "top": y1, "width": x2-x1, "height": y2-y1}
        img = np.array(sct.grab(mon))
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

def ahash(img_bgr, size=8):
    g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (size, size))
    avg = g.mean()
    bits = (g > avg).astype(np.uint8).flatten()
    return hashlib.md5(bits.tobytes()).hexdigest()

def to_point(center_dict):
    if not center_dict: return None
    return {"x": int(center_dict["center"]["x"]), "y": int(center_dict["center"]["y"])}

def read_coords(json_path):
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] 좌표 JSON을 찾을 수 없습니다: {json_path}")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] 좌표 JSON 읽기 실패: {json_path} -> {e}")
        sys.exit(1)

    cats = data.get("categories", [])
    nav = data.get("nav_buttons", {})
    prev_c = nav.get("prev", None)
    next_c = nav.get("next", None)
    return cats, prev_c, next_c

def slugify(name):
    s = re.sub(r"\s+", "_", name.strip())
    s = re.sub(r"[^\w\-\.]+", "", s, flags=re.UNICODE)
    return s or "cat"

def click_xy(x, y, wait=PAUSE):
    pag.moveTo(x, y, duration=0.03)
    pag.click()
    time.sleep(wait)

def wait_for_change(menu_abs, prev_hash, timeout=POLL_TIMEOUT, interval=POLL_INTERVAL):
    t0 = time.time()
    while time.time() - t0 < timeout:
        img = grab_region_abs(*menu_abs)
        h = ahash(img)
        if h != prev_hash:
            return h
        time.sleep(interval)
    return prev_hash  # 변경 실패(타임아웃)

# ---------- 실행 ----------
def run(coords_json, outdir):
    print(f"[WD] 작업 폴더: {os.getcwd()}")
    print(f"[ARGS] coords={coords_json}, outdir={outdir}")
    ensure_dir(outdir)
    print(f"[DIR] outdir 절대경로: {os.path.abspath(outdir)}")

    # 임시 테스트 저장(경로/권한 문제 빠른 진단)
    try:
        ensure_dir(os.path.join(outdir, "_test"))
        dummy = np.zeros((10,10,3), np.uint8)
        save_image(os.path.join(outdir, "_test", "dummy.png"), dummy)
    except Exception as e:
        print(f"[WARN] 테스트 저장 중 예외: {e}")

    win = get_browser_window_rect()
    print(f"[Window] {win}")

    menu_abs = scale_region(BASE_MENU, win, margin=MENU_MARGIN)
    print(f"[CAP] menu_abs={menu_abs}")

    cats, prev_btn, next_btn = read_coords(coords_json)
    print(f"[INFO] categories={len(cats)}, prev={'Y' if prev_btn else 'N'}, next={'Y' if next_btn else 'N'}")
    if not cats:
        print("[ERROR] 좌표 JSON에 categories가 없습니다. 먼저 카테고리 좌표를 생성하세요.")
        sys.exit(1)

    next_pt = to_point(next_btn) if next_btn else None
    prev_pt = to_point(prev_btn) if prev_btn else None

    # 메타 정보 저장: 이미지별 menu_abs를 기록
    meta = {"images": {}}

    for ci, cat in enumerate(cats, start=1):
        cname = cat.get("name") or f"cat{ci}"
        cslug = slugify(cname)
        cdir = os.path.join(outdir, cslug)
        ensure_dir(cdir)

        cc = cat.get("center")
        if not cc:
            print(f"[스킵] {cname}: center 없음")
            continue

        # 카테고리 클릭 → 1초 대기
        click_xy(int(cc["x"]), int(cc["y"]), wait=AFTER_CATEGORY_WAIT)

        # 1페이지로 정렬(가능하면 prev 연타; 각 클릭 후 1초 대기)
        if prev_pt:
            for _ in range(MAX_PREV_TO_FIRST):
                click_xy(prev_pt["x"], prev_pt["y"], wait=AFTER_PAGE_CLICK_WAIT)

        # 첫 페이지 캡처
        img = grab_region_abs(*menu_abs)
        cur_hash = ahash(img)
        print(f"[{cname}] p01 hash={cur_hash} shape={img.shape}")
        fn = f"{cslug}_p01.png"
        save_image(os.path.join(cdir, fn), img)
        meta["images"][fn] = {"menu_abs": list(menu_abs)}

        seen_hashes = {cur_hash}

        # 다음 페이지가 없으면 여기서 종료
        if not next_pt:
            print(f"[{cname}] next 좌표 없음 → 단일 페이지로 종료")
            continue

        # 페이지 넘기며 캡처
        for p in range(2, MAX_PAGES_PER_CAT+1):
            # 다음 클릭 → 1초 대기 → 내용 바뀔 때까지 폴링
            click_xy(next_pt["x"], next_pt["y"], wait=AFTER_PAGE_CLICK_WAIT)
            new_hash = wait_for_change(menu_abs, prev_hash=cur_hash, timeout=POLL_TIMEOUT, interval=POLL_INTERVAL)

            img2 = grab_region_abs(*menu_abs)
            cur_hash = ahash(img2)
            print(f"[{cname}] p{p:02d} hash={cur_hash} (changed_from_poll={new_hash != cur_hash}) shape={img2.shape}")

            # 같은 내용(루프) 감지 시 종료
            if cur_hash in seen_hashes:
                print(f"[{cname}] 순환/반복 감지, p{p:02d}에서 종료")
                break

            fn2 = f"{cslug}_p{p:02d}.png"
            save_image(os.path.join(cdir, fn2), img2)
            meta["images"][fn2] = {"menu_abs": list(menu_abs)}
            seen_hashes.add(cur_hash)

    # 메타 파일 저장
    try:
        with open(os.path.join(outdir, "_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"[OK] 메타 저장 → {os.path.join(outdir, '_meta.json')}")
    except Exception as e:
        print(f"[WARN] 메타 저장 실패: {e}")

    print(f"[OK] 캡처 완료 → {outdir}/<카테고리>/*.png")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--coords", default="kiosk_ui_coords_easyocr.json", help="카테고리/네비 좌표 JSON")
    ap.add_argument("--outdir", default="captures", help="이미지 저장 폴더")
    args = ap.parse_args()
    run(args.coords, args.outdir)