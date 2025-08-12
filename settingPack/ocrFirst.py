# kiosk_capture_categories_and_nav_easyocr.py
import os, re, json, time
import numpy as np
import cv2
from mss import mss
import pygetwindow as gw
import easyocr

# ----- 기준 해상도 & 기준 영역 (업데이트 반영) -----
BASE_W, BASE_H = 1080, 1920  # 세로 모드 해상도

# [변경] 카테고리 바 (1080x1920 해상도)
#   Point(x=5, y=81) -> Point(x=720, y=151)
BASE_CAT  = (5, 81, 720, 151)

# [추가] 메뉴 바 (1080x1920 해상도)
#   Point(x=8, y=169) -> Point(x=735, y=1585)
BASE_MENU = (8, 169, 735, 1585)

# [변경] 이전/페이지버튼/다음 버튼 바 (1080x1920 해상도)
#   Point(x=72, y=1821) -> Point(x=685, y=1915)
BASE_NAV  = (72, 1821, 685, 1915)

# 여유 마진 (필요 시 조정) - 마진 제거로 정확한 좌표 사용
CAT_MARGIN  = (0, 0)
NAV_MARGIN  = (0, 0)

HANGUL = re.compile(r"[가-힣]+")

def ensure_dir(p): os.makedirs(p, exist_ok=True)

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
    except:
        pass
    # 제목 키워드 보조
    for kw in ["localhost", "edge", "chrome", "react"]:
        try:
            wins = gw.getWindowsWithTitle(kw)
            if wins:
                w = wins[0]
                return (w.left, w.top, w.right, w.bottom)
        except:
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

# ---------- EasyOCR ----------
def init_reader():
    # ko + en 조합이 안정적
    return easyocr.Reader(['ko','en'], gpu=False, verbose=False)

def easyocr_full_text(reader, img_bgr, scale=3.0, try_invert=True):
    """
    이미지 전처리(확대/CLAHE/샤픈) + 정상/반전 인식 → (poly, text, conf) 리스트 반환
    동일 텍스트 중복 박스는 IoU로 제거
    """
    def preprocess(img, inv=False):
        big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        g = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
        if inv: g = 255 - g
        clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8,8))
        g = clahe.apply(g)
        blur = cv2.GaussianBlur(g, (0,0), 1.0)
        sharp = cv2.addWeighted(g, 1.6, blur, -0.6, 0)
        return sharp

    out = []
    imgs = [preprocess(img_bgr, inv=False)]
    if try_invert:
        imgs.append(preprocess(img_bgr, inv=True))

    for g in imgs:
        res = reader.readtext(g, detail=1, paragraph=False)  # [ [bbox, text, conf], ... ]
        for bbox, txt, conf in res:
            if not txt:
                continue
            poly = [(p[0]/scale, p[1]/scale) for p in bbox]  # 스케일 원복
            out.append((poly, txt.strip(), float(conf)))

    # 중복 제거
    out = dedup_ocr_boxes(out, iou_thr=0.6)
    return out

def poly_to_bbox_center(poly):
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    x1,y1,x2,y2 = int(min(xs)),int(min(ys)),int(max(xs)),int(max(ys))
    cx, cy = (x1+x2)//2, (y1+y2)//2
    return (x1,y1,x2,y2),(cx,cy)

def categories_from_text(boxes, region_abs, y_gap=22, x_gap=45):
    """
    EasyOCR 결과(boxes)에서 한글 텍스트만 추려 같은 줄/인접 글자를 병합하여
    카테고리 항목으로 변환. 절대 좌표(center/bbox)와 score 포함해서 반환.
    """
    x0,y0,_,_ = region_abs
    items=[]
    for poly, txt, conf in boxes:
        if not HANGUL.search(txt):
            continue
        x1,y1,x2,y2 = poly_to_bbox(poly)
        items.append({"txt":txt, "conf":conf, "bbox":[x1,y1,x2,y2]})
    if not items:
        return []

    # y로 줄 그룹화
    items.sort(key=lambda i: i["bbox"][1])
    lines=[]
    for it in items:
        if not lines or abs(it["bbox"][1] - lines[-1][-1]["bbox"][1]) > y_gap:
            lines.append([it])
        else:
            lines[-1].append(it)

    # 같은 줄 x로 정렬 + 인접 병합
    cats=[]
    for line in lines:
        line.sort(key=lambda i: i["bbox"][0])
        cur=None
        for it in line:
            x1,y1,x2,y2 = it["bbox"]
            if cur is None:
                cur = {"txt":it["txt"], "conf":it["conf"], "bbox":[x1,y1,x2,y2]}
                continue
            # 옆에 붙은 글자면 병합 검토
            if x1 - cur["bbox"][2] <= x_gap:
                # 거의 같은 위치로 중복 인식된 동일 단어면 텍스트는 유지하고 점수/bbox만 갱신
                if bbox_iou(tuple(cur["bbox"]), (x1,y1,x2,y2)) >= 0.6 and it["txt"].replace(" ","") == cur["txt"].replace(" ",""):
                    cur["conf"] = max(cur["conf"], it["conf"])
                    cur["bbox"]  = [min(cur["bbox"][0], x1), min(cur["bbox"][1], y1),
                                    max(cur["bbox"][2], x2), max(cur["bbox"][3], y2)]
                else:
                    # 진짜로 옆 글자면 이어붙이기
                    cur["txt"]  += it["txt"]
                    cur["conf"] = max(cur["conf"], it["conf"])
                    cur["bbox"] = [min(cur["bbox"][0], x1), min(cur["bbox"][1], y1),
                                   max(cur["bbox"][2], x2), max(cur["bbox"][3], y2)]
            else:
                cats.append(cur)
                cur = {"txt":it["txt"], "conf":it["conf"], "bbox":[x1,y1,x2,y2]}
        if cur:
            cats.append(cur)

    # 절대 좌표 + 반복 텍스트 컷
    def squash_repeat(s):
        s2 = s.replace(" ","")
        mid = len(s2)//2
        if len(s2)%2==0 and s2[:mid]==s2[mid:]:
            return s2[:mid]
        return s2

    out=[]
    for c in cats:
        x1,y1,x2,y2 = c["bbox"]; cx, cy = (x1+x2)//2, (y1+y2)//2
        name = squash_repeat(c["txt"])
        out.append({
            "name": name,
            "center": {"x": x0+cx, "y": y0+cy},
            "bbox": [x0+x1, y0+y1, x0+x2, y0+y2],
            "score": round(float(c["conf"]), 3)
        })

    out.sort(key=lambda c: c["bbox"][0])
    # 근접 중복 제거 (좌→우 15px 이내면 더 높은 score 선택)
    dedup=[]
    for c in out:
        if dedup and (c["bbox"][0] - dedup[-1]["bbox"][2]) < 15:
            if c["score"] > dedup[-1]["score"]:
                dedup[-1] = c
        else:
            dedup.append(c)
    return dedup

def nav_from_text(reader, nav_img, nav_abs):
    x0,y0,_,_ = nav_abs
    boxes = easyocr_full_text(reader, nav_img, scale=3.2, try_invert=True)

    prev_btn, next_btn = None, None
    for poly, txt, conf in boxes:
        t = txt.lower().strip()
        (x1,y1,x2,y2),(cx,cy) = poly_to_bbox_center(poly)
        hit_prev = any(k in t for k in ["이전","prev","previous"]) or txt in ["<","◀","«"]
        hit_next = any(k in t for k in ["다음","next"]) or txt in [">","▶","»"]
        if hit_prev:
            prev_btn = {"text":txt, "score":round(conf,3),
                        "center":{"x":x0+cx,"y":y0+cy},
                        "bbox":[x0+x1,y0+y1,x0+x2,y0+y2]}
        if hit_next:
            next_btn = {"text":txt, "score":round(conf,3),
                        "center":{"x":x0+cx,"y":y0+cy},
                        "bbox":[x0+x1,y0+y1,x0+x2,y0+y2]}
    return prev_btn, next_btn

def poly_to_bbox(poly):
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))

def bbox_iou(a, b):
    ax1, ay1, ax2, ay2 = a; bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2-ix1), max(0, iy2-iy1)
    inter = iw*ih
    area_a = max(0, ax2-ax1)*max(0, ay2-ay1)
    area_b = max(0, bx2-bx1)*max(0, by2-by1)
    union = area_a + area_b - inter if (area_a+area_b-inter)>0 else 1
    return inter/union

def dedup_ocr_boxes(boxes, iou_thr=0.6):
    """
    boxes: [(poly, text, conf), ...]
    같은 텍스트가 bbox가 크게 겹치면(conf가 큰 것만 유지) 중복 제거
    """
    norm = lambda s: s.replace(" ", "")
    kept = []
    for poly, txt, conf in sorted(boxes, key=lambda x: x[2], reverse=True):
        bb = poly_to_bbox(poly)
        dup = False
        for i, (pp, tt, cc) in enumerate(kept):
            if norm(tt) == norm(txt):
                if bbox_iou(poly_to_bbox(pp), bb) >= iou_thr:
                    dup = True
                    break  # 이미 높은 conf가 앞에 옴
        if not dup:
            kept.append((poly, txt, conf))
    return kept

def main():
    ensure_dir("debug_kiosk")
    reader = init_reader()
    time.sleep(0.2)

    win_rect = get_browser_window_rect()
    print("[Window]", win_rect)

    # 영역 스케일링 (업데이트 반영)
    cat_abs  = scale_region(BASE_CAT,  win_rect, margin=CAT_MARGIN)
    nav_abs  = scale_region(BASE_NAV,  win_rect, margin=NAV_MARGIN)
    menu_abs = scale_region(BASE_MENU, win_rect, margin=(0,0))  # 현재 미사용, 정보만 출력

    print("[CAT abs]", cat_abs, " [NAV abs]", nav_abs, " [MENU abs]", menu_abs)

    # 캡처 & 저장
    cat_img = grab_region_abs(*cat_abs)
    nav_img = grab_region_abs(*nav_abs)
    cv2.imwrite("../debug_kiosk/cat_region.png", cat_img)
    cv2.imwrite("../debug_kiosk/nav_region.png", nav_img)

    # 카테고리 추출 (텍스트 기반)
    cat_boxes  = easyocr_full_text(reader, cat_img, scale=3.0, try_invert=True)
    categories = categories_from_text(cat_boxes, cat_abs)

    # 네비 버튼 추출 (텍스트 기반)
    prev_btn, next_btn = nav_from_text(reader, nav_img, nav_abs)

    result = {
        "regions_abs": {
            "category_bar": list(cat_abs),
            "nav_bar": list(nav_abs),
            "menu_area": list(menu_abs)  # 참고용
        },
        "categories": categories,
        "nav_buttons": {"prev": prev_btn, "next": next_btn}
    }
    with open("kiosk_ui_coords_easyocr.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[OK] 저장: kiosk_ui_coords_easyocr.json")
    print(f" - 카테고리: {len(categories)}개")
    print(f" - prev: {'감지' if prev_btn else '미검출'}, next: {'감지' if next_btn else '미검출'}")
    print("디버그: debug_kiosk/cat_region.png, nav_region.png")

if __name__ == "__main__":
    main()
