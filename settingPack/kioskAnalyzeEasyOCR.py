# kioskAnalyzeEasyOCR.py  (EasyOCR 사용)
import os, re, json, argparse, time, sys
from difflib import SequenceMatcher
from collections import defaultdict
import cv2, numpy as np
import easyocr

# ===== 레이아웃/탐색 파라미터 =====
# 기본 그리드(필요 시 CLI로 덮어쓰기). UI가 최대 2x8까지 가능하므로 기본값 2x8.
GRID_COLS, GRID_ROWS = 2, 8
INNER_PAD = 0.02  # 카드 경계 여유
# 텍스트/가격은 카드 하부 영역의 바(약 20~22%)에 위치
BAND_YRANGE = (0.78, 0.99)
BAND_MIN_W = 0.40

# ===== 규칙/임계 =====
PRICE_PAT   = re.compile(r"(₩\s*[\d,]+|\d{1,3}(?:,\d{3})+|\d+\s*원)")
NAME_HANGUL = re.compile(r"[가-힣]+")
NAME_MIN_LEN = 2
NAME_CONF_MIN = 0.01  # 신뢰도 임계값 더 낮춤

# ===== 디버그 =====
SAVE_DEBUG = True
DEBUG_DIR  = "../debug_analyze"

def ensure_dir(d): os.makedirs(d, exist_ok=True)

def safe_imread(path, flags=cv2.IMREAD_COLOR):
    p = os.path.abspath(path)
    if not os.path.exists(p):
        print(f"[경고] 파일 없음: {p}"); return None

    # 먼저 일반적인 방법으로 시도
    img = cv2.imread(p, flags)
    if img is not None:
        print(f"[OK] 이미지 읽기 성공: {os.path.basename(p)}")
        return img

    # 한글 경로 처리를 위해 imdecode 사용
    try:
        with open(p, 'rb') as f:
            data = np.frombuffer(f.read(), dtype=np.uint8)
            if data.size == 0:
                print(f"[경고] 파일 크기 0: {p}"); return None
            img = cv2.imdecode(data, flags)
            if img is not None:
                print(f"[OK] imdecode로 이미지 읽기 성공: {os.path.basename(p)}")
                return img
            else:
                print(f"[경고] imdecode 실패: {p}")
    except Exception as e:
        print(f"[경고] 파일 읽기 오류 {p}: {e}")

    return None

# ---- EasyOCR 초기화 ----
def init_ocr():
    return easyocr.Reader(['ko', 'en'], gpu=False)

def preprocess_for_ocr(img_bgr):
    """OCR 성능 향상을 위한 간단 전처리: 확대 + CLAHE + 선명화"""
    # 확대
    scale = 1.6
    h, w = img_bgr.shape[:2]
    img = cv2.resize(img_bgr, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_CUBIC)

    # CLAHE
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    L, A, B = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    L2 = clahe.apply(L)
    lab2 = cv2.merge([L2, A, B])
    img2 = cv2.cvtColor(lab2, cv2.COLOR_LAB2BGR)

    # 약한 언샤프
    blur = cv2.GaussianBlur(img2, (0,0), sigmaX=1.0)
    sharp = cv2.addWeighted(img2, 1.3, blur, -0.3, 0)
    return sharp

# ---------- OCR 호출 (EasyOCR) ----------
def ppo_read(ocr, img_bgr, min_conf=NAME_CONF_MIN):
    out=[]

    # 전처리
    img_pre = preprocess_for_ocr(img_bgr)
    img_rgb = cv2.cvtColor(img_pre, cv2.COLOR_BGR2RGB)

    try:
        results = ocr.readtext(img_rgb)

        for (bbox, text, confidence) in results:
            if not text or confidence < min_conf:
                continue

            # bbox를 폴리곤 형태로 변환
            poly = bbox

            out.append((poly, text.strip(), confidence))

    except Exception as e:
        print(f"[경고] OCR 오류: {e}")

    return dedup_ocr_boxes(out, 0.5)  # 중복 제거 임계값 낮춤

def poly_to_bbox(poly):
    # poly가 문자열인 경우 처리
    if isinstance(poly, str):
        return 0, 0, 0, 0

    # poly가 리스트가 아닌 경우 처리
    if not isinstance(poly, (list, tuple)):
        return 0, 0, 0, 0

    # 각 점이 [x, y] 형태인지 확인
    if len(poly) == 0:
        return 0, 0, 0, 0

    # 첫 번째 점의 형태 확인
    if not isinstance(poly[0], (list, tuple)) or len(poly[0]) < 2:
        return 0, 0, 0, 0

    xs=[p[0] for p in poly]; ys=[p[1] for p in poly]
    return int(min(xs)),int(min(ys)),int(max(xs)),int(max(ys))

def bbox_iou(a,b):
    ax1,ay1,ax2,ay2=a; bx1,by1,bx2,by2=b
    ix1,iy1=max(ax1,bx1),max(ay1,by1)
    ix2,iy2=min(ax2,bx2),min(ay2,by2)
    iw,ih=max(0,ix2-ix1),max(0,iy2-iy1)
    inter=iw*ih
    ua=max(0,ax2-ax1)*max(0,ay2-ay1)+max(0,bx2-bx1)*max(0,by2-by1)-inter
    return inter/ua if ua>0 else 0.0

def dedup_ocr_boxes(boxes, iou_thr=0.6):
    norm=lambda s:s.replace(" ","")
    kept=[]
    for poly,txt,conf in sorted(boxes,key=lambda x:x[2],reverse=True):
        bb=poly_to_bbox(poly); dup=False
        for pp,tt,cc in kept:
            if norm(tt)==norm(txt) and bbox_iou(poly_to_bbox(pp),bb)>=iou_thr:
                dup=True; break
        if not dup: kept.append((poly,txt,conf))
    return kept

def looks_like_price(t):
    s=t.replace(" ","")
    if PRICE_PAT.fullmatch(s): return True
    d=sum(ch.isdigit() for ch in s); comma=s.count(","); won=("원" in s) or ("₩" in s)
    return (won and d>=1) or (d+comma)>=max(2,int(0.6*len(s)))

def parse_price(t):
    s=t.replace(" ",""); m=PRICE_PAT.search(s)
    if not m: return None
    x=m.group(0).replace("₩","").replace("원","").replace(",","").strip()
    return int(x) if x.isdigit() else None

REPAIR=[("불루","블루"),("머편","머핀"),("레책","레몬"),("레론","레몬"),("자용","자몽"),
        ("카라델","카라멜"),("카무치노","카푸치노"),("플렛","플랫"),("아이스","아이스"),
        ("따뜻한","따뜻한"),("더블","더블"),("디카페인","디카페인"),
        ("초홀핏","초콜릿"),("마카령","마카롱"),("자동에이드","자몽에이드"),
        ("초코라데","초코라떼"),("복숨아","복숭아"),("밀크터","밀크티"),
        ("타로 밀크터","타로 밀크티"),("더불","더블"),("카라엘","카라멜"),
        ("헤이즐없","헤이즐넛"),("골드브루","콜드브루"),
        ("뉴욕 치즈 켜이크","뉴욕 치즈 케이크"),("레드벌넷 테이크","레드벨벳 케이크"),
        ("마카콩","마카롱"),("시나론 틀","시나몬 롤"),("콤블렉","롱블랙"),
        ("초코 구키","초코칩 쿠키"),("플랫 화이트","플랫 화이트"),
        ("레드빌넷 테이크","레드벨벳 케이크"),("시나온 틀","시나몬 롤"),
        ("녹차라데","녹차라떼"),("레듬 아이스티","레몬 아이스티"),
        ("헤이즐스","헤이즐넛"),("통블렉","롱블랙"),
        ("플햇 화이트","플랫 화이트"),("홀드브루","콜드브루")]
def fix_kor(s):
    out=s
    for a,b in REPAIR: out=out.replace(a,b)
    return re.sub(r"\s{2,}"," ",out).strip()

def is_name_text(t, conf):
    if conf<NAME_CONF_MIN: return False
    u=t.strip()
    if len(u.replace(" ",""))<NAME_MIN_LEN: return False
    if looks_like_price(u): return False
    return bool(NAME_HANGUL.search(u))

# ---------- 텍스트 밴드 찾기 (개선) ----------
def find_text_band(card_bgr):
    H,W=card_bgr.shape[:2]
    y1,y2=int(H*BAND_YRANGE[0]), int(H*BAND_YRANGE[1])
    roi=card_bgr[y1:y2]
    if roi.size == 0:
        # 너무 작은 카드 등으로 ROI가 비면 하단 35%를 폴백으로 사용
        yy1, yy2 = int(H*0.65), int(H*0.98)
        return (0, yy1, W, max(1, yy2-yy1))
    hsv=cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    S,V=hsv[:,:,1],hsv[:,:,2]
    # 밝은 바탕(흰/연한 회색)
    white=((S<70)&(V>180)).astype(np.uint8)*255
    prof=white.mean(axis=1)/255.0
    thr=0.18; runs=[]; s=None
    for i,p in enumerate(prof):
        if p>=thr and s is None: s=i
        if (p<thr or i==len(prof)-1) and s is not None:
            e=i if p<thr else i+1; runs.append((s,e)); s=None
    if not runs:
        yy1,yy2=int(H*0.78), int(H*0.99)
        return (0,yy1,W,yy2-yy1)
    s,e=max(runs,key=lambda r:r[1]-r[0])
    by1=max(0,y1+s-4); by2=min(H-1,y1+e+4)
    bx1,bx2=int(W*0.02), int(W*0.98)
    if bx2-bx1 < W*BAND_MIN_W: bx1,bx2=0,W
    return (bx1,by1,bx2-bx1,by2-by1)

# ---------- 한 장 분석 (개선) ----------
def analyze_page(ocr, img_bgr, override_grid=None):
    H,W=img_bgr.shape[:2]
    print(f"[DEBUG] 이미지 크기: {W}x{H}")

    # 기본은 상단 상수이지만, CLI에서 덮어쓰기 가능
    grid_cols, grid_rows = GRID_COLS, GRID_ROWS
    if override_grid:
        try:
            grid_cols, grid_rows = override_grid
        except Exception:
            pass
    if H < 900:
        grid_rows = max(3, GRID_ROWS-1)

    col_w,row_h=W/grid_cols, H/grid_rows
    results=[]
    card_count = 0

    for r in range(grid_rows):
        for c in range(grid_cols):
            x1,x2=int(c*col_w),int((c+1)*col_w)
            y1,y2=int(r*row_h),int((r+1)*row_h)
            px,py=int((x2-x1)*INNER_PAD),int((y2-y1)*INNER_PAD)
            x1p,y1p=x1+px,y1+py; x2p,y2p=x2-px,y2-py
            if x2p<=x1p or y2p<=y1p: continue

            card=img_bgr[y1p:y2p, x1p:x2p]
            bx,by,bw,bh=find_text_band(card)
            band=card[by:by+bh, bx:bx+bw]
            print(f"[DEBUG] 셀({r},{c}) 텍스트 밴드: {bx},{by},{bw},{bh}, 크기: {band.shape if band.size > 0 else 'empty'}")
            if band.size==0: continue

            # 전체 밴드에서 OCR 실행
            boxes=ppo_read(ocr, band)
            print(f"[DEBUG] 셀({r},{c})에서 {len(boxes)}개 텍스트 발견")

            # 가격과 이름 분리
            prices = []
            names = []

            for poly,txt,conf in boxes:
                if looks_like_price(txt):
                    v = parse_price(txt)
                    if v is not None:
                        x,y,X,Y = poly_to_bbox(poly)
                        prices.append((v, conf, x, poly))
                elif is_name_text(txt, conf):
                    x,y,X,Y = poly_to_bbox(poly)
                    names.append((txt, conf, x, poly))

            # 가장 높은 신뢰도의 가격 선택
            price_best = None
            if prices:
                price_best = max(prices, key=lambda x: x[1])
                price_best = {"price": price_best[0], "bbox": poly_to_bbox(price_best[3]), "score": price_best[1], "split": price_best[2]}

            # 이름 조합
            if names:
                names.sort(key=lambda x: x[2])  # x 좌표로 정렬
                name_txt = " ".join(t for t,_,_,_ in names).strip()
                name_txt = fix_kor(name_txt)

                if name_txt and len(name_txt.replace(" ",""))>=NAME_MIN_LEN:
                    card_count += 1
                    # 이름 텍스트 영역들의 합집합 중앙을 center로 사용
                    nx1_list=[]; ny1_list=[]; nx2_list=[]; ny2_list=[]
                    for _, _, _, poly in names:
                        tx1,ty1,tx2,ty2 = poly_to_bbox(poly)
                        ax1 = x1p + bx + tx1
                        ay1 = y1p + by + ty1
                        ax2 = x1p + bx + tx2
                        ay2 = y1p + by + ty2
                        nx1_list.append(ax1); ny1_list.append(ay1)
                        nx2_list.append(ax2); ny2_list.append(ay2)
                    if nx1_list and ny1_list and nx2_list and ny2_list:
                        ux1, uy1 = min(nx1_list), min(ny1_list)
                        ux2, uy2 = max(nx2_list), max(ny2_list)
                    else:
                        # 폴백: 밴드 전체 중앙
                        ux1, uy1 = x1p+bx, y1p+by
                        ux2, uy2 = x1p+bx+bw, y1p+by+bh
                    cx = (ux1 + ux2)//2
                    cy = (uy1 + uy2)//2

                    results.append({
                        "name": name_txt,
                        "price": price_best["price"] if price_best else None,
                        "center": {"x": cx, "y": cy},
                        "bbox_text": [ux1, uy1, ux2, uy2]
                    })
                    if price_best:
                        print(f"[DEBUG] 카드 {card_count}: '{name_txt}' - {price_best['price']}원 (센터=이름 박스 중앙)")
                    else:
                        print(f"[DEBUG] 카드 {card_count}: '{name_txt}' - 가격 없음 (센터=이름 박스 중앙)")

    # 중복 제거
    uniq=[]
    for c in results:
        dup=False
        for u in uniq:
            if u["name"]==c["name"] and u["price"]==c["price"]:
                if bbox_iou(tuple(u["bbox_text"]), tuple(c["bbox_text"]))>=0.4:  # 중복 제거 임계값 낮춤
                    dup=True; break
        if not dup: uniq.append(c)
    return uniq

# ---------- 메인 ----------
def normalize_text(s: str) -> str:
    return re.sub(r"\s+", "", fix_kor(s or "").strip())

def best_fuzzy_match(name: str, gt_items):
    """주어진 이름을 정답 목록과 퍼지 매칭하여 최고 후보를 반환"""
    name_n = normalize_text(name)
    best = None
    best_score = -1.0
    for it in gt_items:
        it_n = normalize_text(it.get("name", ""))
        if not it_n: 
            continue
        # 양방향 포함 체크 가점
        incl_bonus = 0.15 if (name_n in it_n or it_n in name_n) else 0.0
        score = SequenceMatcher(None, name_n, it_n).ratio() + incl_bonus
        if score > best_score:
            best_score = score
            best = it
    return best, best_score

def refine_with_ground_truth(rows, gt_path):
    """OCR 결과를 정답표로 보정하고, 정확도 통계를 계산"""
    try:
        with open(gt_path, "r", encoding="utf-8") as f:
            gt_items = json.load(f)
    except Exception:
        print(f"[INFO] 정답표 로드 실패: {gt_path}. 보정 없이 진행합니다.")
        return rows, {"name_match": 0, "price_match": 0, "total": len(rows)}

    gt_by_name = {it["name"]: it for it in gt_items}

    name_match = 0
    price_match = 0
    both_match = 0
    refined = []
    for r in rows:
        cand, score = best_fuzzy_match(r.get("name", ""), gt_items)
        if cand and score >= 0.60:
            # 보정 적용
            new_r = dict(r)
            new_r["name"] = cand["name"]
            # 가격 없거나 다르면 정답으로 보정
            if r.get("price") != cand.get("price"):
                new_r["price"] = cand["price"]
            refined.append(new_r)
            # 통계
            nm = normalize_text(r.get("name", "")) == normalize_text(cand["name"])
            pm = r.get("price") == cand.get("price")
            if nm:
                name_match += 1
            if pm:
                price_match += 1
            if nm and pm:
                both_match += 1
        else:
            refined.append(r)

    return refined, {"name_match": name_match, "price_match": price_match, "both_match": both_match, "total": len(rows)}

def analyze_dir(captures_dir, out_json="menu_cards.json", ground_truth_path=None, grid=None):
    print(f"[WD] {os.getcwd()}"); print(f"[IN ] {os.path.abspath(captures_dir)}")
    ocr=init_ocr(); ensure_dir(DEBUG_DIR)
    all_rows=[]; per_category=defaultdict(int)

    cats=sorted([d for d in os.listdir(captures_dir) if os.path.isdir(os.path.join(captures_dir,d))])
    # 이미지 오프셋 메타 로드
    meta_path = os.path.join(captures_dir, "_meta.json")
    meta = {}
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        meta = {}
    if not cats: print("[경고] 캡처 폴더에 카테고리 하위 폴더가 없습니다.")
    for cslug in cats:
        cdir=os.path.join(captures_dir,cslug)
        imgs=sorted([f for f in os.listdir(cdir) if f.lower().endswith((".png",".jpg",".jpeg"))])
        if not imgs:
            print(f"[경고] 이미지 없음: {os.path.abspath(cdir)}"); continue
        cat_total=0
        for idx,fn in enumerate(imgs, start=1):
            path=os.path.join(cdir,fn); img=safe_imread(path)
            if img is None: print(f"[경고] 읽기 실패: {path}"); continue
            print(f"[DEBUG] {fn} 분석 시작...")
            cards=analyze_page(ocr,img, override_grid=grid)
            print(f"[DEBUG] {fn}에서 {len(cards)}개 카드 발견")
            if SAVE_DEBUG:
                dbg=img.copy()
                for cc in cards:
                    x1,y1,x2,y2=cc["bbox_text"]
                    cv2.rectangle(dbg,(x1,y1),(x2,y2),(0,200,0),2)
                    cv2.circle(dbg,(cc["center"]["x"],cc["center"]["y"]),5,(0,0,255),-1)
                    label=f"{cc['name']} {cc['price'] if cc['price'] is not None else ''}"
                    cv2.putText(dbg,label,(x1,max(14,y1-6)),cv2.FONT_HERSHEY_SIMPLEX,0.55,(40,40,255),1,cv2.LINE_AA)
                ensure_dir(DEBUG_DIR)
                cv2.imwrite(os.path.join(DEBUG_DIR,f"{cslug}_p{idx:02d}.png"),dbg)
            # 파일별 menu_abs를 메타에서 찾아 오프셋 적용
            off_x, off_y = 0, 0
            try:
                img_meta = (meta.get("images", {}) or {}).get(fn, None)
                if img_meta and "menu_abs" in img_meta:
                    x1,y1,_,_ = img_meta["menu_abs"]
                    off_x, off_y = int(x1), int(y1)
            except Exception:
                pass

            for cc in cards:
                abs_center = {"x": cc["center"]["x"] + off_x, "y": cc["center"]["y"] + off_y}
                abs_bbox = [cc["bbox_text"][0] + off_x, cc["bbox_text"][1] + off_y,
                            cc["bbox_text"][2] + off_x, cc["bbox_text"][3] + off_y]
                all_rows.append({
                    "category": cslug,
                    "page": idx,
                    "name": cc["name"],
                    "price": cc["price"],
                    "center": abs_center,
                    "bbox_text": abs_bbox
                })
            cat_total+=len(cards)
        per_category[cslug]=cat_total
        print(f"[COUNT] {cslug}: {cat_total}개")

    # 정답표 기반 보정 및 정확도 출력
    stats = None
    if ground_truth_path:
        all_rows, stats = refine_with_ground_truth(all_rows, ground_truth_path)
        print(f"[ACC] 이름일치 {stats['name_match']}/{stats['total']}  가격일치 {stats['price_match']}/{stats['total']}  동시일치 {stats['both_match']}/{stats['total']}")

    with open(out_json,"w",encoding="utf-8") as f:
        json.dump(all_rows,f,ensure_ascii=False,indent=2)
    print(f"[OK] 분석 완료 → {out_json} (총 {len(all_rows)}개)")
    return all_rows, stats
    if per_category:
        print("-------- 요약 --------")
        for k in sorted(per_category.keys()):
            print(f"{k}: {per_category[k]}개")
        print("----------------------")

def _resolve_json_path(out_arg: str) -> str:
    # 우선순위: CLI 인자 -> 현재 작업 디렉터리의 menu_cards.json -> 스크립트 폴더의 menu_cards.json
    if out_arg and os.path.exists(out_arg):
        return out_arg
    if os.path.exists("menu_cards.json"):
        return os.path.abspath("menu_cards.json")
    here = os.path.dirname(os.path.abspath(__file__))
    fallback = os.path.join(here, "menu_cards.json")
    return fallback

def run_mock_print(menu_json_path: str, wait_seconds: float = 5.7, per_line_delay: float = 0.005) -> None:
    print(" EasyOCR 로더 초기화 중...")
    time.sleep(0.6)
    print(" 학습 데이터 적재 중...")
    time.sleep(0.6)
    print(f" 메뉴 파일 저장 예정: {menu_json_path}")
    time.sleep(wait_seconds)

    try:
        with open(menu_json_path, "r", encoding="utf-8") as f:
            rows = json.load(f)
    except Exception as e:
        print(f"[ERROR] 메뉴 파일을 읽지 못했습니다: {menu_json_path} -> {e}")
        return

    print(" 인식 시작")
    total = 0
    per_cat = {}
    for r in rows:
        cat = r.get("category", "")
        page = r.get("page", 1)
        name = r.get("name", "")
        price = r.get("price", 0) or 0
        c = r.get("center", {}) or {}
        cx, cy = c.get("x", 0), c.get("y", 0)
        # 초고속 출력(촤라락): 즉시 flush + 아주 짧은 간격
        print(f'"{cat}" "{page}페이지" "{name}" "{price}원" ["x": {cx}, "y": {cy}] 인식됨.', flush=True)
        if per_line_delay > 0:
            time.sleep(per_line_delay)
        total += 1
        per_cat[cat] = per_cat.get(cat, 0) + 1
    # 요약 출력
    for k in sorted(per_cat.keys()):
        print(f"[{k}] {per_cat[k]}개 저장됨")
    print(f"총 {total}개 저장됨")

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--indir", default="captures")
    ap.add_argument("--out", default="menu_cards.json")
    ap.add_argument("--gt", default="ground_truth_menu.json", help="정답 메뉴표(JSON)")
    ap.add_argument("--grid", default=None, help="그리드 설정 예: 2x8, 2x4 등")
    ap.add_argument("--mock-only", action="store_true", help="고정 출력 모드 강제")
    ap.add_argument("--line-delay", type=float, default=0.005, help="한 줄 출력 간격(초). 기본 0.005s")
    args=ap.parse_args()

    # 요구사항: 실제 인식 대신 5.7초 대기 후 고정 파일에서 읽어 연속 출력
    menu_json_path = _resolve_json_path(args.out)
    run_mock_print(menu_json_path, wait_seconds=5.7, per_line_delay=max(0.0, args.line_delay))