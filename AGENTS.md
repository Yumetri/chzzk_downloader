# AGENTS.md

> 치지직(Chzzk) 통합 녹화·VOD 다운로더 프로젝트의 AI 에이전트 개발 가이드입니다.  
> 본 프로젝트에 참여하는 모든 AI 에이전트는 코드 작성, 리팩터링, 디버깅 시 아래 아키텍처, 엔지니어링 방어 규칙, 빌드/테스트 파이프라인을 엄격히 준수해야 합니다.

---

## 1. 프로젝트 개요 & 핵심 스택

- **목적**: 치지직(Chzzk) 실시간 방송 녹화 및 VOD 다운로드 고신뢰성 데스크톱 GUI 애플리케이션 (Hitomi Downloader 아키텍처 벤치마킹)
- **현재 구현 스코프**: **치지직 VOD 다운로드 전용** (URL 파싱, 메타데이터 추출, 최고화질 다운로드, fMP4/FFmpeg Muxing, 네이버 쿠키 세션). *실시간 라이브 자동 녹화 및 채널 감시 폴링은 향후 로드맵 항목입니다.*
- **주요 런타임 스택**:
  - **언어/런타임**: Python >= 3.12, [uv](https://docs.astral.sh/uv/) (Hatchling 빌드 백엔드)
  - **GUI 프레임워크**: PyQt6 (6.7+), PyQt6-WebEngine (네이버 웹뷰 로그인)
  - **미디어 엔진**: `yt-dlp` (VOD 메타데이터 파싱/다운로드), `FFmpeg`/`FFprobe` (Muxing 및 HLS 실시간 녹화)
  - **코드 품질 & 테스트**: Ruff (Linter/Formatter), Pyrefly (타입 체커), Pytest, pytest-qt

---

## 2. 디렉터리 구조 및 모듈 책임 (Structure & Responsibilities)

### 2.1 디렉터리 레이아웃
```text
chzzk_downloader/
├── AGENTS.md                          # [SSOT 관제탑] AI 에이전트 개발 가이드 (아키텍처, 방어규칙, 파이프라인)
├── readme.md                          # [사용자 대문] 프로젝트 소개, 주요 기능, 실행 방법
├── .github/workflows/ci.yml           # CI 파이프라인 (Lint, Type Check, Xvfb Test)
├── docs/                              # 공식 참조 규격서 (On-demand 포인터)
│   ├── UI_FEEDBACK_CATALOG.md         # UI 피드백 SSOT (M01~M10, T01~T08, C01~C09 전수 카탈로그)
│   ├── AI_ADVERSARIAL_VALIDATOR_GUIDE.md # 서브에이전트 적대적 검증 독립 프롬프트 (A~L 체크리스트)
│   └── HITOMI_CHZZK_FEATURE_DESIGN_SPEC.md # 치지직 도메인/설정 스펙 및 로드맵 기획서
├── src/chzzk_downloader/
│   ├── config.py                      # 전역 상수, URL 엔드포인트, 기본 경로
│   ├── main.py                        # QApplication 진입점
│   ├── core/                          # [비즈니스/엔진 레이어] UI 완전 비의존
│   └── gui/                           # [프레젠테이션 레이어] PyQt6 위젯 및 QThread 워커
├── tests/                             # 통합/단위 테스트 스위트 (260+ 테스트)
│   ├── conftest.py                    # QtWebEngine 선행 import 필수 설정
│   └── unit/                          # TaskManager, Worker 단위/동시성 테스트
├── reports/                           # [산출물] 설계·트레이드오프 학습용 HTML 보고서 (.gitignore 격리)
└── tools/preview_ui_feedbacks.py      # UI 피드백 쇼케이스 직접 실행기
```

### 2.2 모듈별 책임 및 공개 인터페이스 표

| 레이어 | 모듈 | 책임 및 핵심 규칙 |
| :--- | :--- | :--- |
| **core** | `task_models.py` | `TaskStatus`(9대 생명주기 Enum C01~C09), `TaskProgress`, `TaskSpec` 불변 데이터클래스 정의 |
| **core** | `task_queue.py` | 스레드 세이프티 VOD 대기열 관리 및 순서 제어 |
| **core** | `task_manager.py` | 중앙 관제탑 (슬롯 동시성 제어, RLock 상태 가드, Thread-Local 이벤트 디스패치) |
| **core** | `ytdlp.py` | yt-dlp 래퍼 (VOD 스트림/포맷 추출, 외부 API 격리) |
| **core** | `ffmpeg_manager.py` | FFmpeg/FFprobe 6단계 자동 탐색/온디맨드 부트스트랩 및 버전 프로빙 |
| **core** | `cookie_manager.py` | Netscape 쿠키 저장, 파싱, 네이버 세션 유효성 검증 |
| **core** | `settings_manager.py`| `AppSettings` JSON 영속화 (6대 필드: `download_dir`, `default_quality`, `file_extension`, `vod_auto_download`, `ffmpeg_path`, `ffprobe_path`) |
| **core** | `url_parser.py` | 치지직 VOD URL 정규식 검증 및 VOD ID 파싱 |
| **gui** | `main_window.py` | 메인 윈도우, URL 입력바, 작업 카드 목록 스크롤, 전역 워커 Teardown 수명 관리 |
| **gui** | `task_card.py` | 개별 작업 카드 (C01~C09 9대 상태 렌더링, 액션 툴바, 치지직 뱃지, 진단창 연동) |
| **gui** | `task_info_window.py`| 작업 상세 오류 및 진단 정보를 제공하는 비모달(Modeless) 팝업 창 |
| **gui** | `dialogs.py` | 공통 모달 대화상자 (`ask_confirm_dialog`를 통한 M01~M10 구현) |
| **gui** | `toast.py` | 다크 테마 반투명 알약형 오버레이 토스트 (T01~T08) |
| **gui** | `workers.py` | `QThread` 기반 비동기 워커 (`VodDownloadWorker`, `FFmpegBootstrapWorker` 등) |

---

## 3. 핵심 엔지니어링 방어 규칙 (코드 품질 극대화)

### 3.1 동시성 & 상태 머신: 수집-디스패치(Collect-then-Dispatch) 원칙 [필수]
1. **락 블록 내부 Qt Signal emit 절대 금지 (Deadlock 방지)**:
   - 락(`with self._lock:`) 내부에서 시그널을 방출하면, 슬롯에 바인딩된 핸들러가 다시 `TaskManager` 메서드를 호출할 때 Lock Inversion 데드락이 발생합니다.
   - **반드시** 락 내부에서는 상태 갱신과 이벤트 수집만 수행하고, 락을 벗어난 뒤 디스패치해야 합니다:
   ```python
   # [권장 표준 패턴]
   events: list[tuple] = []
   with self._lock:
       self._statuses[task_id] = new_status
       events.append(("status_changed", task_id, old_status, new_status))
   
   # 락 해제 후 Thread-Local 큐를 통해 순차 방출
   self._enqueue_and_dispatch_events(events)
   ```
2. **동시성 도구의 역할 엄격 분리**:
   - `self._lock (threading.RLock)`: **멀티스레드 간** 공유 상태(`_statuses`, `_specs`, 슬롯 카운트) 동기화 전담.
   - `self._thread_local.event_queue`: **동일 스레드 내** 동기 시그널 재호출 시 콜스택 폭주(RecursionError) 방지 및 이벤트 순서 평탄화 전담 (멀티스레드 락을 대체하지 않음).
3. **원자성 & 멱등성 계약**:
   - 작업 완료/실패 시 슬롯 반환과 다음 대기 작업의 슬롯 할당은 단일 `_lock` 블록 내에서 원자적으로 처리합니다.
   - `report_*` 계열 메서드는 미등록 작업이나 유효하지 않은 선행 상태에 대해 `return False`로 안전하게 무시(멱등성 보장)해야 합니다.
   - 작업 취소(`cancel_task`: STOPPED 전이, 슬롯 반환)와 작업 삭제(`remove_task`: 큐/목록 제거, `task_removed` 방출)의 책임을 명확히 분리합니다.

### 3.2 UI 넌블로킹 & PyQt C++ 수명주기 방어 [필수]
1. **메인 UI 스레드 블로킹 절대 금지**:
   - 네트워크 요청, 파일 I/O, subprocess(`ffmpeg`, `yt-dlp`), sleep은 반드시 `QThread` 워커에서 실행합니다.
2. **PyQt C++ 객체 파괴 방어 (`sip.isdeleted`)**:
   - 비동기 시그널 도착 시점에 사용자가 카드를 삭제했을 수 있으므로, 동적 UI 위젯 접근 시 C++ 파괴 여부를 필수 검증합니다:
   ```python
   if card is not None and not card.is_deleted and not sip.isdeleted(card):
       card.set_task_status(new_status)
   ```
3. **워커 안전 종료(Teardown) 패턴**:
   - 창 닫기(`closeEvent`) 시 실행 중인 워커는 부모 연결을 끊고(`setParent(None)`), 시그널을 `disconnect()`한 후 모듈 전역 집합(`_DETACHED_WORKERS`)으로 이전하여 `QThread: Destroyed while thread is still running` 크래시를 원천 차단합니다.
4. **계층 간 캡슐화 강제**:
   - UI 레이어가 Core 레이어의 private 속성(`_specs`, `_statuses` 등)에 직접 접근하는 것을 절대 금지하며, 반드시 공식 getter(`get_task_status()`, `get_task_spec()` 등)만 사용합니다.

### 3.3 UI 피드백 동기화 5단계 규칙 (`docs/UI_FEEDBACK_CATALOG.md`)
1. **디자인 규격**:
   - 모달 창 제목은 **`Chzzk Downloader`** 로 통일.
   - 질문형 모달은 Yes/No를 금지하고 `ask_confirm_dialog`를 사용해 **`[확인]` / `[취소]`** 명시 및 '확인' 버튼 기본 포커스/하이라이트 적용.
   - 문체: 질문형 `~하시겠습니까?`, 안내형 `~합니다.` / `~되었습니다.`.
   - 작업 카드 실패 상태(`FAILED_*`): 3번 위치(진행 텍스트)를 숨기고(`hide()`), 4번 위치에 말풍선 에러 버튼(`TaskInfoWindow`) 연동.
2. **동기화 절차**:
   - 카탈로그 표 갱신(`docs/UI_FEEDBACK_CATALOG.md`) ➔ 쇼케이스 등록(`feedback_showcase.py`) ➔ 자동화 테스트 통과(`tests/test_ui_feedback_catalog.py`) ➔ 프리뷰 육안 검증(`tools/preview_ui_feedbacks.py`).

---

## 4. 빌드, 린트, 테스트 파이프라인 (Commands)

```bash
# 1. 의존성 설치 및 동기화
uv sync --dev                     # 기본 동기화
uv sync --dev --system-certs      # SSL/기업 프록시 환경

# 2. 코드 품질 검사 (Ruff & Pyrefly)
uv run ruff check .               # 린트 검사
uv run ruff check . --fix         # 린트 자동 수정
uv run ruff format --check .      # 포맷 검사
uv run ruff format .              # 포맷 적용
uv run pyrefly check              # 정적 타입 검사 (0 errors 유지)

# 3. 테스트 실행 (Pytest)
uv run pytest                     # 전체 테스트 (260+ 테스트)
uv run --no-sync pytest           # 오프라인/캐시 기반 테스트
uv run pytest tests/test_ui_feedback_catalog.py # UI 카탈로그 규격 검증
uv run pytest tests/unit/test_task_manager.py   # 동시성 매니저 검증

# 4. UI 피드백 프리뷰 실행
uv run python tools/preview_ui_feedbacks.py
```
> **CI 파이프라인**: GitHub Actions(`.github/workflows/ci.yml`)에서 PR 시 Lint(Ruff), Type(Pyrefly), Test(Xvfb Pytest) 3단계가 헤드리스로 자동 검증됩니다.

---

## 5. 작업 워크플로우 & 에이전트 행동 지침

### 5.1 엄격한 TDD & 가짜 테스트(Cheat Testing) 4대 블랙리스트 [금지령]
버그 수정 시 **반드시 실패하는 재현 테스트를 먼저 작성**한 후 수정을 진행합니다.  
테스트 통과를 위해 아래의 가짜 테스트 행위를 엄격히 금지합니다:
1. `assert mock.called` 사용 금지 (오타 시 항상 True) ➔ `mock.assert_called_once()` 사용.
2. 비동기 대기 시 `time.sleep()` 남발 금지 ➔ `qtbot.waitUntil(lambda: condition, timeout=1000)` 사용.
3. `assert result is not None`, `assert True` 등 무의미한 항진 assertion 작성 금지.
4. 테스트 블록 내 광범위한 `try ... except Exception: pass`로 예외 묵살 금지.

### 5.2 무맥락 적대적 검증 (Adversarial Validation)
동시성, 상태 머신, 백그라운드 워커 수정 후에는 **[docs/AI_ADVERSARIAL_VALIDATOR_GUIDE.md](file:///c:/Users/이홍원/Desktop/code_training/chzzk_downloader/docs/AI_ADVERSARIAL_VALIDATOR_GUIDE.md)**의 A~L 체크리스트(동시성 원자성, UI 넌블로킹, 테스트 무결성, 리소스 수명 등)를 바탕으로 무맥락 서브 에이전트 감사를 거쳐야 합니다.

### 5.3 세션 인계 정보 (Handoff) 표준 출력 양식
세션 종료 또는 작업 완료 시, 추측이 아닌 `git status / diff` 기반의 결정적 사실만 아래 포맷으로 출력합니다:

```markdown
## 세션 인계 정보 (Handoff)

### 1. 이번 세션에서 변경된 파일 (`git status --porcelain` 기준)
- ...

### 2. 파일별 변경 요약
- path/to/file.py: 한 줄 요약

### 3. 검증 상태 (실제 실행 결과)
- ruff / pyrefly / pytest 통과 결과

### 4. 미해결·이월 항목 및 다음 세션 착수 파일
- ...

### 5. 아키텍처 학습용 HTML 분석 보고서 (`explain-diff-html`)
- 보고서 링크: [`file:///c:/path/to/reports/YYYY-MM-DD-explanation-<slug>.html`](file:///c:/path/to/reports/YYYY-MM-DD-explanation-<slug>.html)
- 핵심 설계 결정 & 트레이드오프: (채택된 설계와 기각된 대안 요약 1~2줄)
*(유의미한 아키텍처/설계 변경이 없는 자잘한 수정 세션의 경우 "해당 없음" 기재)*

### 6. 스킬 및 자동화 제안 (Skill & Automation Candidates)
- **추천 스킬/도구명**: (예: `vod-error-diagnose`, `quick-verify` 등 또는 "해당 없음")
- **제안 이유**: (이번 작업 중 복잡했거나 반복될 절차, 비전문가 사용자 관점에서의 기대 효과)
- **구성 내용**: (매뉴얼 제목, 한 줄 설명, 스킬 호출 시 AI가 대신 수행할 핵심 절차 요약)
```

### 5.4 설계 결정 및 트레이드오프 학습용 HTML 보고서 생성 규칙 (`explain-diff-html`) [필수]
본 프로젝트는 코드의 기계적 변경 나열이 아닌, **시스템 설계적 결정과 아키텍처 트레이드오프의 깊이 있는 학습**을 중시합니다.  
신규 기능 도입, 동시성/상태 머신 제어, 비동기 수명주기 설계, 대규모 리팩터링 등 **학습 가치가 있는 유의미한 아키텍처 변경 작업**이 완료되면, 세션 인계 전 반드시 `explain-diff-html` 스킬을 사용하여 대화형 HTML 보고서를 생성해야 합니다.

1. **발동 및 제외 기준 (Filtering)**:
   - **발동 (필수)**: 슬롯 동시성, 비동기 워커 수명주기, 상태 전이 원자성, 신규 엔진 레이어 추가 등 설계적 고민과 트레이드오프가 수반된 작업.
   - **제외 (스킵)**: 단순 오타/주석 교정, UI 라벨/문구 변경, 린트/포맷 단독 적용, 단일 단순 유닛 테스트 보완 등.

2. **보고서 서술 철학 & 4대 핵심 섹션**:
   - **서술 스타일**: Martin Kleppmann 스타일의 명료하고 서사적인 문체. 기술적 본질에 집중하며 ASCII 아트 금지(심플한 HTML/CSS 다이어그램 사용).
   - **Background**: 시스템 아키텍처 맥락 (초보자를 위한 시스템 원리 + 본 변경과의 연관 배경).
   - **Intuition**: 설계의 핵심 직관. **왜 이 설계를 선택했고, 대안은 왜 배제되었는지(트레이드오프)**를 토이 데이터와 시각적 다이어그램으로 설명.
   - **Code**: 줄 단위가 아닌 아키텍처 단위로 묶은 고차원 코드 워크스루 (`<pre>` 태그 및 `white-space: pre-wrap` 필수).
   - **Quiz**: 독자가 변경의 실질적인 메커니즘과 트레이드오프를 체득했는지 검증하는 대화형 객관식 5문항 (클릭 시 정답/해설 제공).

3. **저장 위치 및 Git 트래킹 차단 원칙**:
   - **저장 디렉터리**: 현재 프로젝트 루트의 `reports/` 폴더에 저장합니다 (디렉터리가 없으면 자동 생성).
   - **파일명 규격**: `reports/YYYY-MM-DD-explanation-<slug>.html` (날짜 기반 정렬).
   - **Git 트래킹 차단**: `.gitignore`에 `reports/`가 등록되어 있으므로 Git status/commit을 일절 오염시키지 않습니다.

4. **세션 인계 연동**:
   - 생성 완료 후 세션 인계 정보 5번에 로컬 브라우저 오픈용 `file:///` 링크를 첨부하여 사용자가 즉시 학습할 수 있도록 제출합니다.

### 5.5 스킬 및 단축 워크플로우 자발적 제안 규칙 [필수]
에이전트는 사용자가 비전문가임을 항상 인지하고, 세션 종료 시 본 세션에서 수행한 작업 중 '스킬(Skill)'이나 '단축 명령(Makefile/단축 스크립트)'으로 체계화할 가치가 있는 항목을 적극적으로 발굴하여 제안해야 합니다:

1. **발굴 기준**:
   - **다단계 복잡 절차**: 3단계 이상의 순차 명령이나 검증이 필요했던 작업 (예: 특정 UI/엔진 상태 동기화, UI 피드백 카탈로그 5단계 동기화 등).
   - **명령어 실수 방지**: 파라미터가 길어 AI가 명령을 지어내다 오타/실수를 유발하기 쉬운 명령 조합 (예: `uv run --no-sync ...` 일괄 검사 등).
   - **정형화된 재발 작업**: 다음 개발 스프린트나 버그 픽스 시 동일하게 다시 발생할 가능성이 높은 작업 절차.
2. **비전문가 친화적 설명 원칙**:
   - 난해한 기술 용어 대신, **"이 스킬을 만들어 두면 앞으로 어떤 상황에서 편리한지"**, **"AI가 무엇을 대신해 주는지"** 비전문가 눈높이의 쉬운 언어로 설명합니다.
3. **실행 연결**:
   - 사용자가 "그거 스킬로 만들어줘"라고 승인하면, 즉시 `.agents/skills/<name>/SKILL.md` (또는 전역 경로)에 표준 형식으로 구조화하여 등록합니다.


---

## 6. Git 커밋 및 브랜치 규칙

- **브랜치**: `<이슈번호>-<타입>-<티켓ID>-<설명>` (예: `19-feat-t0111-create-download-task`)
- **커밋 메시지**: `<타입>(<스코프>): <한국어 설명> (#<이슈번호>)` (Conventional Commits)
  - 타입: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`
