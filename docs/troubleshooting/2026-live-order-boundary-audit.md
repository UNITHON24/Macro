# Live 주문 경계 사전 감사

- 발견일: 2026-07-15
- 범위: 로컬 주문 허브, 순차 키오스크 실행, UIA grounding
- 상태: 코드와 회귀 테스트로 수정, Windows acceptance 필요
- 운영 영향: 공개 배포 전 발견되어 확인된 사용자·결제 영향 없음

## 맥락

절대 좌표 구현을 의미 기반 폐쇄루프로 바꾼 뒤, 실제 팀 백엔드 payload와 프론트엔드의
접근성 트리를 fixture로 사용해 live 주문 경계를 다시 검토했다. 개별 클릭의 postcondition은
검증하고 있었지만 주문 사이의 물리적 화면 상태, 로컬 HTTP 신뢰 경계와 중첩 action control은
별도 실패 경계였다.

## 기대와 실제

기대 동작은 한 고객의 장바구니와 결제 준비 화면이 다음 주문과 섞이지 않고, 승인된 음성
백엔드와 클라이언트만 영속 주문 큐를 사용할 수 있으며, 실제 데모 화면의 메뉴 action이
하나로 결정되는 것이었다.

감사에서 다음 문제가 재현됐다.

1. 성공 또는 일부 성공 뒤 결과가 terminal로 저장되어, 고객 인계 전 다음 주문을 claim할 수 있었다.
2. 주문 허브가 loopback에만 bind됐지만 인증이 없어 다른 로컬 프로세스가 주문을 넣거나 결과를 ACK할 수 있었다.
3. tokenless dry-run 주문이 같은 SQLite DB에 남으면 나중의 live 세션이 claim할 수 있었다.
4. 팀 프론트엔드의 메뉴 카드 `ListItem`과 중첩된 추가 `Button`이 비슷한 점수를 받아 실제 메뉴가 모호성 오류로 거부됐다.
5. 제목 기반 UIA 검색과 OCR window handle 고정이 서로 다른 창을 가리킬 수 있었고 offscreen·disabled control도 후보에 포함됐다.

## 영향

- 이전 고객의 장바구니나 결제 모달 위에서 다음 주문이 시작될 수 있었다.
- 인증되지 않은 로컬 주문이 포인터 동작으로 이어질 수 있었다.
- 안전 검사를 위해 추가한 모호성 거부가 실제 데모의 정상 메뉴 action까지 차단했다.
- 숨겨진 배경 control이나 제목이 비슷한 다른 창이 grounding 후보가 될 수 있었다.

해당 경로는 공개 배포되지 않았고 실제 Windows 키오스크 acceptance 전이므로 확인된 사용자,
금액 또는 개인정보 영향은 없다.

## 근본 원인

- 주문 결과의 성공·실패와 고객 인계가 끝난 kiosk session을 같은 terminal 의미로 취급했다.
- `127.0.0.1` bind를 충분한 인증 경계로 간주했고 dry-run과 live가 영속 큐를 공유한다는 점을 분리하지 않았다.
- 텍스트 유사도와 일반 role bonus만으로 부모·자식 action의 의미 강도를 구분했다.
- UIA provider와 OCR provider의 창 선택 계약이 하나의 native handle로 통합되지 않았다.

## 검토한 대안

- 성공 ACK 직후 장바구니를 자동 초기화: 고객 결제·취소 상태를 임의로 변경할 수 있어 거부했다.
- 일정 시간이 지나면 다음 주문 허용: 물리 상태를 증명하지 못하므로 거부했다.
- tokenless dry-run 큐를 별도 DB로 분리: 모드 전환과 파일 설정 오류가 남아 모든 모드 인증을 선택했다.
- nested control 하나를 좌표나 automation id로 고정: 다른 키오스크 재사용성이 낮아 정확한 action label과 role evidence를 선택했다.
- 창 제목 substring만 유지: 같은 제목의 창과 overlay를 배제하지 못해 native handle 통합을 선택했다.

## 해결

- live 장바구니가 한 번이라도 검증되면 `awaiting_handoff`로 보존하고 고객 인계·취소와 화면 초기화를 확인하기 전 다음 claim을 막는다.
- 결과가 불확실하면 더 강한 `uncertain` 상태를 유지한다. 부분 수량 성공도 `cart_mutated`로 추적한다.
- 주문 허브의 모든 endpoint에 32자 이상 설치별 `KIOSK_ORDER_TOKEN`과 constant-time 비교를 적용했다.
- 팀 Spring 백엔드가 같은 환경변수를 읽어 `X-Macro-Token` 헤더로 전달하도록 연동 계약을 맞췄다.
- launcher는 이미 사용 중인 9999 포트를 신뢰하지 않고 거부하며 새 hub 프로세스 생존을 확인한다.
- 실제 데모의 `메뉴명 장바구니에 추가` label을 강한 증거로 사용하고 action role이 일반 텍스트보다 우선하도록 했다.
- UIA와 OCR를 같은 native window handle에 고정하고 offscreen·disabled·창 밖 UIA control을 제외했다.

## 검증

- 성공, 부분 항목 성공, 부분 수량 성공 뒤 다음 주문 차단
- `awaiting_handoff` 운영자 해제 전 global claim 거부
- token 누락·불일치 거부와 올바른 header 승인
- 팀 백엔드의 `X-Macro-Token` 전달 단위 테스트
- 실제 프론트엔드 구조를 재현한 부모 ListItem·중첩 Button grounding
- exact native window handle과 UIA visibility filter
- macOS pure-core 전체 테스트 통과와 PR에서 실행할 Linux·Windows CI workflow 구성

현재 macOS 환경에서는 실제 Windows UIA, DPI, 물리 포인터, 고객 인계 화면을 end-to-end로
검증하지 못했다. 비운영 Windows 키오스크 acceptance가 남은 gate다.

## 회귀 방지

- 물리 UI 변경과 메시지 ACK를 하나의 transaction으로 표현하지 않는다.
- 성공 결과도 kiosk session이 초기화될 때까지 다음 주문을 허용하지 않는다.
- dry-run을 인증 우회 경계로 사용하지 않는다.
- fixture의 실제 접근성 트리를 후보 모호성 테스트에 보존한다.
- 창 관찰 provider는 하나의 native identity를 공유한다.

## 인터뷰에서 설명할 질문

- 성공한 주문도 왜 큐의 terminal 상태가 아닌가?
- localhost 서비스에도 인증이 필요한 이유는 무엇인가?
- dry-run 주문이 live 큐로 넘어가는 문제를 어떻게 막았는가?
- 부모와 자식이 모두 클릭 가능한 접근성 트리에서 오동작을 어떻게 방지했는가?
- 물리 UI 자동화에서 exactly-once 대신 어떤 보장을 선택했는가?
