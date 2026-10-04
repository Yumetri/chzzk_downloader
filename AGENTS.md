# AGENTS.md

치지직 VOD 다운로더 (Python 3.12, PyQt6, yt-dlp, FFmpeg, uv). 이 파일의 엔지니어링 규칙은 전부 `tools/check_rules.py`, Ruff, Pyrefly, Pytest로 **기계 검증**되며, 협업·소통 프로세스는 `docs/AGENT_WORKFLOW.md`를 엄격히 준수한다.

## 0. 완료 조건 (이 4개가 모두 통과해야 "완료"라고 말할 수 있다)

```bash
uv run ruff check . && uv run ruff format --check .
uv run pyrefly check
uv run python tools/check_rules.py      # R/T/M 규칙 래칫 검사
xvfb-run -a uv run pytest          # Windows는 xvfb-run 생략
```

실패한 검사를 통과시키려고 규칙 예외(`noqa`, `type: ignore`, 기준값 상향)를 추가하지 않는다. 기준값(`tools/rule_baseline.json`)은 **내리는 방향으로만** 수정한다.

## 1. 계층 규칙 (R1)

| 디렉터리 | import 가능 | import 금지 |
| :--- | :--- | :--- |
| `core/` | 표준 라이브러리, `yt_dlp`, `core/*` | `PyQt6`, `gui/*` |
| `gui/` | `core/*`, `PyQt6` | — |

- 상태와 슬롯 수는 `core.TaskManager` 한 곳에만 있다. 위젯은 `status`를 직접 대입하지 않고 `TaskManager` 이벤트로만 바꾼다.
- `TaskManager`는 GUI 스레드에서만 호출한다. 워커 스레드는 시그널만 보내고 `TaskManager`를 직접 호출하지 않는다. 따라서 `TaskManager`에 락·thread-local을 추가하지 않는다.
- 오류를 실패 상태로 분류하는 함수는 `core/errors.py`의 `classify_error()` 하나뿐이다. 문자열 키워드 매칭을 다른 파일에 복제하지 않는다.

## 2. 크기 제한 (R2)

- `src/` 파일 1개 ≤ 400줄. 함수 1개 ≤ 50문장(Ruff `PLR0915`), 복잡도 ≤ 10(`C901`).
- 400줄을 넘기게 되면 기능을 추가하기 전에 파일부터 나눈다.

## 3. 금지 구문 (R3, R4)

| 금지 | 대신 |
| :--- | :--- |
| `hasattr(self, ...)`, `getattr(self, "x", None)` | `__init__`에서 모든 속성을 타입과 함께 선언한다 |
| `hasattr(obj, ...)`로 타입 추측 | 정확한 타입 힌트 또는 `Protocol` |
| `sip.isdeleted(...)` | 위젯이 비동기 시그널을 직접 받지 않게 한다 (§4) |
| `except Exception:` / `except: pass` | 구체 예외(`OSError`, `yt_dlp.utils.DownloadError` 등)를 잡고 `logger.exception`으로 남긴다 |
| `self.window()`로 상위 창을 찾아 호출 | 시그널을 내보내고 상위가 연결한다 |
| 다른 클래스의 `_private` 속성 접근 | 공개 메서드를 추가한다 |
| 프로덕션 코드 안의 테스트 전용 분기 (`receivers()==0` 등) | 테스트에서 fake를 주입한다 |

## 4. 워커 수명주기 (R5)

1. 워커는 `MainWindow._workers: dict[str, Worker]`에만 등록한다. 카드 위젯은 워커를 모른다.
2. 중지: `worker.cancel()`만 호출한다. **슬롯 반환(`report_stopped`)은 `worker.finished` 수신 시에만** 한다. 중지 버튼에서 슬롯을 반환하지 않는다.
3. 같은 `task_id`의 이전 워커가 살아 있으면 새 워커를 시작하지 않는다.
4. 파일 정리는 워커가 자기가 만든 경로 목록(`self.created_paths`)만 지운다. `glob("{stem}*")` 같은 접두어 와일드카드 삭제는 금지한다.
5. 앱 종료 시 실행 중인 다운로드가 있으면 확인 모달을 띄우고, 모든 워커를 `cancel()` 후 `wait()`로 종료를 기다린다. 워커를 전역 집합으로 떼어내 방치하지 않는다.

## 5. GUI 스레드 (R6)

GUI 스레드에서 `subprocess.*`, `urlopen`, `mkdir`, `stat`, `exists`, FFmpeg 프로빙을 호출하지 않는다. 필요하면 워커에서 미리 계산해 결과만 시그널로 받는다.

## 6. 테스트 (T)

| 금지 | 대신 |
| :--- | :--- |
| `time.sleep()` | `qtbot.waitUntil(cond, timeout=...)`, `qtbot.waitSignal(sig)` |
| `assert m.called`, `assert a.called or b.called` | `m.assert_called_once_with(...)` |
| `obj._private` 단언 | 공개 API·시그널·디스크 결과로 단언 |
| 이미 `start()`된 스레드의 `run` 교체 | 시작 전에 fake 워커를 주입 |
| 실제 네트워크 접근 | `yt_dlp.YoutubeDL`, `urlopen`을 patch |

- 버그 수정은 **수정 전에 실패하는 테스트**를 먼저 커밋 단위에 포함한다.
- 파일 삭제·정리 테스트에는 반드시 "지우면 안 되는 이웃 파일이 남아 있다"는 음성 단언을 넣는다.
- 동시성 테스트는 "실제 동시 실행 워커 수 ≤ 슬롯 수"를 단언한다.
- 프로덕션에서 호출되지 않는 코드를 위한 테스트를 쓰지 않는다. 호출처가 없으면 코드를 지운다.

## 7. 명명 (M)

- 테스트 파일·함수 이름은 **동작**을 쓴다: `test_stop_releases_slot_only_after_worker_exits`.
- `P0`, `adversarial`, `결함`, `round5` 같은 감사·티켓 단어를 파일명·함수명·주석에 쓰지 않는다. 이슈 번호는 커밋 메시지에만 쓴다.

## 8. Git

- 브랜치: `<이슈번호>-<타입>-<설명>` / 커밋: `<타입>(<스코프>): <설명> (#<이슈번호>)`
- push, 브랜치 전환, PR 코멘트는 사용자가 승인한 뒤에만 한다.

## 9. 협업 라이프사이클 7단계 상태 머신 (`docs/AGENT_WORKFLOW.md` 준수)

에이전트는 모든 이슈·기능 구현 시 임의로 단계를 건너뛰지 않고 아래 P1~P7 상태 머신을 순차적으로 전이한다:

| Phase | 단계명 | 진입 및 완료 가드 (Transition Guard) | 핵심 산출물 |
| :--- | :--- | :--- | :--- |
| **P1** | **Plan & Briefing** | 사용자 요구 분석 ➔ 기술적 답변 및 작업 계획·TDD 시나리오 브리핑 ➔ 사용자 승인 | 계획 브리핑 |
| **P2** | **TDD Red** | 프로덕션 수정 전 실패하는 테스트 작성 ➔ `pytest` 실패(Red) 실행 로그 기계 확인 | 실패 테스트 |
| **P3** | **TDD Green** | 최소 프로덕션 코드 구현 ➔ 해당 테스트 통과(Green) | 통과 코드 |
| **P4** | **Adversarial Audit** | **에이전트 자발적 서브에이전트 가동** ➔ 엣지 케이스 감사 ➔ 경계값 TDD 보강 | 감사 리포트 & 보강 테스트 |
| **P5** | **4대 기계 검증** | `ruff`, `pyrefly`, `check_rules.py`, `pytest` 전수 실행 ➔ 0 error 통과 | 4대 검증 로그 |
| **P6** | **Handoff & Report** | 아키텍처 변경 시 `reports/*.html` 생성 ➔ `AGENT_WORKFLOW.md` §3 6대 Handoff 양식 출력 | HTML 보고서, Handoff |
| **P7** | **Ship** | 사용자 최종 승인 ➔ Git 커밋, 데스크톱 동기화(`desktop-sync`), 푸시/PR | Git 커밋 & PR |

- **UI 카탈로그 4자 동기화**: UI 피드백(모달 M, 토스트 T, 작업 카드 C) 추가·수정 시 `docs/UI_FEEDBACK_CATALOG.md` (SSOT), `feedback_showcase.py`, `tools/preview_ui_feedbacks.py`, `tests/test_ui_feedback_catalog.py`의 4자 일괄 동기화를 엄격히 준수한다.
- **기계 검증 가드**: 상태 전이 및 완료 검증은 `tools/check_workflow.py`로 기계적으로 확인한다.

