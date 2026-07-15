# Windows CI 이식성 실패

- 발견일: 2026-07-15
- 범위: SQLite 주문 큐, 테스트 경로 검증, Windows 로그 출력
- 상태: 근본 원인 수정 후 Linux·Windows CI 재검증
- 운영 영향: PR 검증 중 발견되어 사용자·주문·결제 영향 없음

## 맥락과 재현

의미 기반 자동화와 영속 주문 큐를 Linux와 Windows에서 검증하는 PR 품질 workflow를
실행했다. Ubuntu job은 통과했지만 Windows job은 논리 검증을 마친 뒤 임시 SQLite 파일을
삭제하지 못했고, 한국어 상태 메시지와 설정 경로 테스트에서도 실패했다.

## 기대와 실제

- 기대: 각 큐 작업이 transaction을 끝내고 데이터베이스 파일 handle을 즉시 해제한다.
- 실제: 테스트가 끝날 때 `orders.sqlite3`가 잠겨 `WinError 32`가 발생했다.
- 기대: 같은 테스트와 진단 출력이 운영체제와 무관하게 동작한다.
- 실제: Windows runner의 cp1252 출력에서 한국어가 `UnicodeEncodeError`를 일으켰고,
  POSIX 구분자를 포함한 문자열 suffix 검사가 Windows 경로를 거부했다.

## 근본 원인

Python의 SQLite connection context manager는 commit 또는 rollback만 수행하고 connection을
닫지는 않는다. macOS와 Linux에서는 참조 해제 시점 때문에 문제가 드러나지 않았지만,
Windows의 파일 잠금 규칙에서는 열린 handle이 임시 디렉터리 삭제를 막았다. 나머지 두
실패는 CI 출력 인코딩과 경로 표현을 특정 운영체제의 기본값으로 가정한 결과였다.

## 검토한 대안

- 테스트 cleanup 재시도 또는 강제 삭제: 실제 handle 누수를 숨기므로 제외했다.
- WAL 모드 제거: 동시 접근 특성을 약화하면서 connection lifecycle 문제는 남아 제외했다.
- 한국어 로그 제거: 운영자에게 필요한 진단 정보를 잃으므로 제외했다.
- 경로 문자열을 슬래시로 치환: 의미 단위 경로 비교보다 취약해 제외했다.

## 해결

- 모든 주문 큐 접근을 전용 context manager로 통합해 transaction 종료 뒤 connection을
  `finally`에서 명시적으로 닫는다.
- CI Python UTF-8 모드를 활성화해 한국어 진단 출력의 플랫폼 차이를 제거한다.
- 설정 파일 검증은 `pathlib.Path.parts`로 의미 있는 마지막 경로 요소를 비교한다.

## 검증과 회귀 방지

- 전체 표준 라이브러리 테스트와 syntax compilation을 macOS에서 다시 실행한다.
- 같은 품질 workflow를 Ubuntu와 Windows에서 모두 통과시킨다.
- 임시 파일 삭제 실패를 sleep이나 cleanup 재시도로 우회하지 않는다.
- 새 파일 경로 테스트는 운영체제별 문자열 구분자에 의존하지 않는다.

## 인터뷰에서 설명할 질문

- SQLite connection context manager가 connection을 닫지 않는다는 점이 왜 중요한가?
- 파일 handle 누수가 Windows에서 먼저 드러난 이유는 무엇인가?
- 이식성 실패를 테스트 우회가 아니라 lifecycle 수정으로 해결한 이유는 무엇인가?
