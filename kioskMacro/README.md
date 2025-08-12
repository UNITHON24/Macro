# 🎤 음성인식 키오스크 매크로

실시간 음성 인식을 통해 키오스크 주문을 자동으로 처리하는 Python 매크로입니다.

## ✨ 주요 기능

- **실시간 음성 녹음**: WebSocket을 통한 백엔드 서버와의 실시간 통신
- **자동 주문 처리**: 음성 인식 결과를 바탕으로 메뉴 자동 선택 및 장바구니 담기
- **스마트 마이크 제어**: 주문 처리 중 마이크 종료 방지, 1분 무음 자동 종료
- **드래그 가능한 UI**: 화면 어디든 이동 가능한 마이크 오버레이 버튼

## 🚀 설치 및 실행

### 1. 필요한 라이브러리 설치

```bash
py -m pip install -r requirements.txt
```

### 2. 프로그램 실행

```bash
py run_voice.py
```

## ⚙️ 설정

### 환경 변수 설정 (선택사항)

```bash
# UI 좌표 및 메뉴 카드 파일 경로
set KIOSK_UI_COORDS=path/to/kiosk_ui_coords_easyocr.json
set KIOSK_MENU_CARDS=path/to/menu_cards.json

# 백엔드 서버 설정
set KIOSK_AUDIO_WS_URL=ws://localhost:8080/chat
set KIOSK_ORDERS_URL=http://localhost:9999/orders

# 음성 인식 설정
set KIOSK_SAMPLE_RATE=16000
set KIOSK_VAD_LEVEL=3
set KIOSK_SILENCE_TIMEOUT_SEC=60

# 매크로 동작 설정
set KIOSK_DRY_RUN=0  # 1: 실제 클릭 안함, 0: 실제 클릭
```

## 🎯 사용법

### 1. 마이크 오버레이

- **녹음 시작**: 마이크 버튼 클릭
- **녹음 종료**: 마이크 버튼 다시 클릭 또는 1분 무음
- **위치 이동**: 버튼을 드래그하여 원하는 위치로 이동
- **프로그램 종료**: ESC 키

### 2. 음성 주문 예시

```
"화이트 모카 1개"
"레몬에이드 2개"
"아메리카노"
```

## 🔧 백엔드 서버 요구사항

### WebSocket 엔드포인트 (`ws://localhost:8080/api/chat`)

**연결 시 전송되는 데이터:**
```json
{
  "type": "start",
  "format": {
    "sample_rate": 16000,
    "encoding": "pcm_s16le",
    "channels": 1
  }
}
```

**음성 데이터**: PCM 16-bit little-endian 형식으로 실시간 전송

**서버 응답:**
```json
{
  "type": "stop"
}
```

### 주문 API (`http://localhost:9999/api/orders`)

**응답 형식:**
```json
[
  {"name": "화이트 모카", "count": 1},
  {"name": "레몬에이드", "count": 2}
]
```

또는

```json
{
  "type": "final",
  "items": [
    {"name": "화이트 모카", "count": 1},
    {"name": "레몬에이드", "count": 2}
  ]
}
```

## 📁 파일 구조

```
kioskMacro/
├── run_voice.py          # 메인 실행 파일
├── requirements.txt      # 필요한 라이브러리 목록
├── README.md            # 이 파일
└── voice/               # 음성 인식 모듈
    ├── __init__.py
    ├── overlay.py       # 마이크 오버레이 UI
    ├── audio.py         # 음성 스트리밍
    ├── audio_ws.py      # WebSocket 클라이언트
    ├── orders_client.py # 주문 수신 클라이언트
    ├── macro.py         # 주문 처리 매크로
    ├── navigator.py     # 키오스크 네비게이션
    ├── index_loader.py  # 메뉴 인덱스 로더
    └── config.py        # 설정 관리
```

## 🎮 매크로 동작 원리

1. **음성 인식**: 사용자 음성을 실시간으로 녹음하여 백엔드 서버로 전송
2. **주문 수신**: 백엔드에서 처리된 주문 정보를 HTTP API로 수신
3. **메뉴 매칭**: 음성 인식 결과를 `menu_cards.json`과 매칭하여 최적의 메뉴 찾기
4. **자동 네비게이션**: 
   - 해당 카테고리 클릭 (1페이지로 이동)
   - 필요한 페이지까지 다음 버튼으로 이동
   - 메뉴 중앙 좌표 클릭하여 장바구니에 담기
5. **마이크 제어**: 주문 처리 중에는 마이크 종료 방지

## ⚠️ 주의사항

- **마이크 권한**: 마이크 접근 권한이 필요합니다
- **화면 해상도**: `kiosk_ui_coords_easyocr.json`의 좌표가 현재 화면 해상도와 일치해야 합니다
- **백엔드 서버**: WebSocket과 HTTP API 서버가 실행 중이어야 합니다
- **테스트 모드**: `KIOSK_DRY_RUN=1`로 설정하여 실제 클릭 없이 테스트 가능합니다

## 🐛 문제 해결

### 마이크가 작동하지 않는 경우
- 마이크 권한 확인
- `sounddevice` 라이브러리 설치 확인
- 백엔드 WebSocket 서버 연결 상태 확인

### 매크로가 제대로 작동하지 않는 경우
- `kiosk_ui_coords_easyocr.json`과 `menu_cards.json` 파일 경로 확인
- 화면 해상도와 좌표값 일치 여부 확인
- `KIOSK_DRY_RUN=1`로 설정하여 로그 확인

### 백엔드 연결 오류
- WebSocket 서버 (`ws://localhost:8080/api/chat`) 실행 상태 확인
- HTTP API 서버 (`http://localhost:9999/api/orders`) 실행 상태 확인
- 방화벽 및 네트워크 설정 확인

## 📝 로그 예시

```
🎤 음성인식 키오스크 매크로 시작...
==================================================
✅ tkinter
✅ pyautogui
✅ sounddevice
✅ webrtcvad
✅ websockets
✅ requests
✅ numpy
✅ UI 좌표: ../settingPack/kiosk_ui_coords_easyocr.json
✅ 메뉴 카드: ../settingPack/menu_cards.json
✅ WebSocket: ws://localhost:8080/api/chat
✅ 주문 API: http://localhost:9999/api/orders

🚀 마이크 오버레이 시작...
💡 마이크 버튼을 클릭하여 녹음을 시작하세요
💡 드래그하여 위치를 이동할 수 있습니다
💡 ESC 키로 종료할 수 있습니다
[INIT] 메뉴 인덱스 로드 성공
[INIT] 주문 수신 시작
[WS] WebSocket 시작
[REC] 녹음 시작
[WS] 연결 시도: ws://localhost:8080/api/chat
[WS] 연결 성공
[ORDERS] new items: [{'name': '화이트 모카', 'count': 1}]
[ORDER] 주문 처리 시작 - 마이크 종료 방지
[MACRO] 주문 처리 시작: 1개 항목
[MACRO] 항목 1: '화이트 모카' 1개 처리 중...
[MATCH] '화이트 모카' → '화이트 모카' / 커피 p1 @ (500, 300)
[NAV] 카테고리 '커피' → (200, 100)
[CLICK] (200, 100)
[NAV] 카테고리 '커피' 선택 완료
[NAV] 이미 1페이지에 있음
[CLICK] '화이트 모카' 담기 @ (500, 300) (1/1)
[CLICK] (500, 300)
[MACRO] '화이트 모카' 1개 담기 완료
[MACRO] 주문 처리 완료: 1/1 성공
[NAV] 네비게이션 상태 초기화
[ORDER] 주문 처리 완료 - 마이크 종료 가능
```
