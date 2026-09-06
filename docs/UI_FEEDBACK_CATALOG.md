# 치지직 다운로더 UI 피드백(모달 & 토스트) 카탈로그 규격서

이 문서는 치지직 다운로더 애플리케이션 내의 모든 **모달 대화상자(Modal Dialog)** 및 **토스트 알림(Toast Notification)**의 문체(Tone & Voice), 디자인, 인터랙션 규격을 체계적으로 일원화 관리하기 위한 공식 가이드라인 및 카탈로그입니다.

새로운 기능을 개발하거나 티켓을 구현할 때 신규 모달/토스트가 추가되거나 기존 문구가 변경되는 경우, **반드시 이 문서를 갱신하고 쇼케이스 도구(`feedback_showcase.py`)와 동기화**해야 합니다.

---

## 1. 디자인 및 문체(Tone & Voice) 기본 원칙

### 1) 모달 대화상자 (Modal Dialog)
* **아웃 프레임(창 제목) 통일**:
  * 모든 모달 대화상자의 윈도우 타이틀바(아웃 프레임)는 **`Chzzk Downloader`** 로 통일하여 일관된 앱 아이덴티티를 유지합니다. 질문 및 안내의 구체적인 내용은 본문 텍스트(`text`)에 명확히 표기합니다.
* **버튼 명칭 통일**:
  * 단순 확인/취소 질문형 모달: **Yes / No 형태를 엄격히 금지**하고, 반드시 **`[확인]`**과 **`[취소]`** 명시적 한글 버튼을 사용합니다.
  * 다중 분기 선택 모달: 사용자가 취할 행동을 직관적으로 알 수 있는 명사/동사형 라벨(예: `[덮어쓰기]`, `[이름 변경]`, `[취소]`)을 사용합니다.
  * 단순 안내/경고 모달: **`[확인]`** 단일 버튼을 사용합니다.
* **버튼 하이라이트 및 기본 포커스**:
  * 승인(확인) 버튼에 **기본 포커스(`msg_box.setDefaultButton(...)` 및 `setFocus()`)**를 반드시 부여하여 사용자가 <kbd>Enter</kbd> 키로 즉시 실행할 수 있게 합니다.
  * 일반 확인 버튼: Primary 파란색 하이라이트 (`background-color: #2563eb; color: white; font-weight: bold;`)
  * 파괴적/위험 확인 버튼(삭제, 초기화 등): Danger 빨간색 하이라이트 (`background-color: #ef4444; color: white; font-weight: bold;`)
  * 취소/보조 버튼: 차분한 다크 그레이 (`background-color: #4b5563; color: white;`)
* **문체 및 어조**:
  * 확인/질문형: 사용자의 의사를 정중히 묻는 **`~하시겠습니까?`** 체를 사용합니다.
  * 설명 문구: 줄바꿈(`\n`)을 적절히 활용하여 첫 줄에 핵심 질문, 둘째 줄에 부가 설명/영향 범위를 명확히 분리합니다.

### 2) 토스트 알림 (Toast Notification)
* **배경 및 다크 테마 통일**:
  * 모든 토스트는 시각적 피로도를 낮추고 일관성을 높이기 위해 **T01과 동일한 어두운 반투명 검은 배경 (`rgba(20, 20, 20, 230)`)**으로 통일합니다.
  * 타입별 구분은 배경색이 아닌 **좌측 상태 아이콘(+, ⚠️, ✕)** 및 테두리 색상으로 정갈하게 표현합니다.
* **내용 맞춤형 유동적 알약(Dynamic Pill) 크기**:
  * 고정된 최소 너비 강제 없이, 메시지와 버튼 길이에 맞추어 알약(Pill) 형태로 컴팩트하게 축소/확장됩니다. 짧은 문구는 휑한 빈 공간 없이 아담하게 표시되며, 긴 VOD URL이 입력될 때만 창 너비(최대 92%) 한도 내에서 한 줄로 시원하게 자동 확장됩니다.
* **경고성 토스트 공통 아이콘**:
  * 중복 거부, 세션 만료 등 경고성 토스트에는 노란색 삼각형 느낌표 **`⚠️`** 아이콘을 공통 적용합니다.
* **인증 버튼 아이콘화 및 툴팁**:
  * **쿠키 설정 버튼 (`🍪`)**: 버튼 배경색 없이 투명 아이콘으로 단독 표시되며, 마우스 호버 시에만 은은한 하이라이트와 `쿠키 설정` 툴팁을 제공합니다.
  * **네이버 로그인 버튼 (`N`)**: 브랜드 아이덴티티인 초록색 사각 버튼(`#03c75a`)에 볼드 흰색 `N`으로 표시되며, 마우스 호버 시 `네이버 로그인` 툴팁을 제공합니다.
  * 2초 자동 소멸 토스트는 닫기(`✕`) 버튼을 숨겨 심플함을 극대화하고, 인터랙티브 액션 토스트(T06)에만 호버 스타일이 적용된 닫기(`✕`) 버튼을 제공합니다.
* **유형별 소멸 및 유지 정책**:
  * **일반 안내/성공 (T01, T03, T04, T05)**: 2초 후 자동 페이드아웃 소멸 (`auto_dismiss_ms=2000`).
  * **인터랙티브 액션 토스트 (T06)**: 사용자 조작 전까지 유지.

---

## 2. 모달 대화상자(Modal Dialog) 전수 카탈로그

| ID | 카테고리 | 창 제목 (`title`) | 본문 문구 (`text`) | 버튼 구성 (기본 하이라이트) | 스타일 | 관련 티켓 | 구현 위치 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **M01** | 다운로드 중지 | **Chzzk Downloader** | `정말 중지하시겠습니까?` | `[확인(기본)]` / `[취소]` | Primary 파랑 (`#2563eb`) | T0109 | `TaskCardWidget._confirm_stop_dialog` |
| **M02** | 작업 재다운로드 | **Chzzk Downloader** | `이미 추가한 작업입니다. 다시 다운로드하시겠습니까?` | `[확인(기본)]` / `[취소]` | Primary 파랑 (`#2563eb`) | T0109 | `MainWindow._confirm_redownload_dialog` |
| **M03** | 쿠키 초기화 | **Chzzk Downloader** | `저장된 쿠키를 삭제하시겠습니까?` | `[확인(기본)]` / `[취소]` | Danger 빨강 (`#ef4444`) | T0106, T0108 | `SettingsWindow._on_clear_clicked` |
| **M04** | 파일명 충돌 | **Chzzk Downloader** | `이미 동일한 이름의 파일이 존재합니다:\n{filename}` | `[덮어쓰기]` / `[이름 변경(기본)]` / `[취소]` | Action 회색 + 포커스 | T0109 | `TaskCardWidget._prompt_duplicate_resolution` |
| **M05** | 쿠키 불러오기 결과 | **Chzzk Downloader** | `쿠키를 성공적으로 불러왔습니다.`<br>`쿠키 파일 형식이 올바르지 않습니다: {msg}` | `[확인(기본)]` | Info / Warning | T0106 | `SettingsWindow._on_import_clicked` |
| **M06** | 쿠키 내보내기 결과 | **Chzzk Downloader** | `쿠키를 성공적으로 내보냈습니다.`<br>`쿠키 내보내기에 실패했습니다: {msg}` | `[확인(기본)]` | Info / Warning | T0106 | `SettingsWindow._on_export_clicked` |
| **M07** | 폴더 권한 오류 | **Chzzk Downloader** | `선택한 폴더에 쓰기 권한이 없습니다:\n{path}\n\n다른 폴더를 선택해주세요.` | `[확인(기본)]` | Warning | T0108 | `SettingsWindow._on_choose_folder` |
| **M08** | 네이버 로그인 결과 | **Chzzk Downloader** | `로그인이 확인되어 네이버 쿠키가 저장되었습니다.`<br>`쿠키 저장 중 오류가 발생했습니다: {msg}` | `[확인(기본)]` | Info / Warning | T0106, T0107 | `NaverLoginDialog._on_save_and_close` |


---

## 3. 토스트 알림(Toast Notification) 전수 카탈로그

| ID | 카테고리 | 유형 (`ToastType`) | 표시 문구 (`message`) | 추가 요소 / 버튼 | 소멸 정책 | 관련 티켓 | 구현 위치 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **T01** | URL 추가 동작 | `ToastType.INFO` / `SUCCESS` | `+ [URL]` (파란색 + 흰색, 한 줄 표시) | 없음 (가로 너비 확장) | 2초 자동 소멸 | T0102 | `MainWindow.toast` |
| **T02** | 쿠키 재분석 | *(제거됨)* | *(백그라운드 침묵 자동 재분석으로 전환)* | 없음 | - | T0106 | `MainWindow._on_cookies_updated` |
| **T03** | 진행중 중복 거부 | `ToastType.WARNING` | `⚠️ 이미 추가한 작업입니다.` | 노란색 경고 아이콘 | 2초 자동 소멸 | T0109 | `MainWindow._on_download_clicked` |
| **T04** | 지원하지 않는 URL | `ToastType.ERROR` | `Invalid: {URL}` | 없음 | 2초 자동 소멸 | T0102 | `MainWindow._on_download_clicked` |
| **T05** | VOD 확인 실패 | `ToastType.ERROR` | `Invalid: {URL}`<br>`Login required; Please login\n{URL}` | 줄바꿈 포맷 지원 | 2초 자동 소멸 | T0102, T0103 | `MainWindow._on_vod_check_failed` |
| **T06** | 쿠키 만료 경고 액션 | `ToastType.WARNING` | `⚠️ 쿠키를 갱신하세요` | `[🍪 쿠키설정]` `[N 네이버로그인]` `[✕]` | 사용자 조작 전까지 유지 | T0107 | `MainWindow.toast.show_action_toast` |

---

## 4. 티켓 구현 시 피드백 업데이트 체크리스트

1. [ ] **신규 모달 또는 토스트 추가 시**:
   - 본 문서(`docs/UI_FEEDBACK_CATALOG.md`)의 카탈로그 표에 항목 추가 (ID, 제목, 문구, 버튼, 소멸 규칙).
   - 확인 질문형 모달인 경우 `chzzk_downloader.gui.dialogs.ask_confirm_dialog`를 사용하여 "확인/취소" 및 "확인 하이라이트" 원칙 준수.
2. [ ] **쇼케이스 도구 등록**:
   - `src/chzzk_downloader/gui/feedback_showcase.py`에 해당 항목을 테스트할 수 있는 버튼 추가.
3. [ ] **자동 검증 테스트 확인**:
   - `uv run pytest tests/test_ui_feedback_catalog.py`를 실행하여 문체 및 버튼 규격 검증 통과 확인.
4. [ ] **실행 확인**:
   - `uv run python -m chzzk_downloader.gui.feedback_showcase` 실행 후 눈으로 실제 렌더링 결과 확인.

