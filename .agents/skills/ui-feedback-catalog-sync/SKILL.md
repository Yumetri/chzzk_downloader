---
name: ui-feedback-catalog-sync
description: Use when adding or modifying UI feedback (modals M01~M11, toasts T01~T08, task cards C01~C09) to ensure 3-way synchronization across docs/UI_FEEDBACK_CATALOG.md, feedback_showcase.py, and test_ui_feedback_catalog.py.
---

# UI 피드백 카탈로그 3자 일괄 동기화 매뉴얼 (ui-feedback-catalog-sync)

이 스킬은 프로젝트 내에 새로운 모달 대화상자, 토스트 알림 또는 작업 카드 상태가 추가·변경될 때, AI 에이전트가 단일 진실 공급원(SSOT) 규칙에 따라 문서, 쇼케이스 도구, 테스트 코드를 누락 없이 일괄 갱신하기 위한 표준 워크플로우입니다.

---

## 1. 3자 동기화 타깃 파일

1. **공식 규격서**: `docs/UI_FEEDBACK_CATALOG.md` (SSOT)
2. **인터랙티브 쇼케이스**: `src/chzzk_downloader/gui/feedback_showcase.py` (및 실행기 `tools/preview_ui_feedbacks.py`)
3. **카탈로그 무결성 테스트**: `tests/test_ui_feedback_catalog.py`

---

## 2. 에이전트 표준 5단계 동기화 절차

### 1단계: 공식 규격서 갱신 (`docs/UI_FEEDBACK_CATALOG.md`)
- **신규 모달 (Mxx)**:
  - 창 제목은 반드시 **`Chzzk Downloader`** 로 통일.
  - 질문형 모달은 Yes/No를 엄격히 금지하고 `[확인]` / `[취소]` 한글 버튼 및 확인 기본 하이라이트(Primary `#2563eb` 또는 Danger `#ef4444`) 명시.
  - 카탈로그 2번 표에 ID, 카테고리, 본문 문구, 버튼 구성, 구현 함수 경로를 등록.
- **신규 토스트 (Txx)**:
  - 배경은 다크 테마 `rgba(20, 20, 20, 230)` 알약 형태.
  - 카탈로그 3번 표에 ID, 유형, 표시 문구, 소멸 정책(2초 자동소멸 또는 유지) 등록.
- **작업 카드 상태 (Cxx)**:
  - 1번(작업명), 2번(호버 툴바), 3번(상태/진행률), 4번(컨트롤/아이콘) 규격 명시.
  - 실패 상태는 3번 위치를 숨김(`hide()`) 처리하고 4번 위치에 말풍선 에러 버튼(`TaskInfoWindow`) 연동.

### 2단계: 인터랙티브 쇼케이스 도구 연동 (`src/chzzk_downloader/gui/feedback_showcase.py`)
- **모달/토스트 탭**:
  - `FeedbackShowcaseWindow`의 모달/토스트 레이아웃에 데모 트리거 버튼 추가 (`self._add_btn`).
  - 클릭 핸들러(`_demo_modal_*`, `_demo_toast_*`)를 구현하여 하단 결과 로그 콘솔에 실행 결과(`_log`)를 출력하도록 연결.
- **작업 카드 갤러리 탭**:
  - `_create_cards_tab`에 해당 상태의 `TaskCardWidget`을 추가하거나, 모의 데이터(`TaskProgress` 등)를 주입하여 개발자가 시각적으로 즉시 검증할 수 있도록 배치.

### 3단계: 자동화 검증 테스트 보강 (`tests/test_ui_feedback_catalog.py`)
- `test_feedback_showcase_modals_use_unified_title`에 신규 모달 데모 메서드 호출 및 `captured_titles` 개수 업데이트.
- 질문형 모달인 경우 `test_confirm_modals_use_korean_confirm_cancel_and_default_highlight`에 `(ID, text, is_danger)` 튜플 추가.
- 카탈로그 테스트 실행:
  ```bash
  uv run --no-sync pytest tests/test_ui_feedback_catalog.py
  ```

### 4단계: 코드 포맷 및 정적 검사 통과
```bash
uv run --no-sync ruff check . --fix
uv run --no-sync ruff format .
uv run --no-sync pyrefly check
```

### 5단계: 데스크톱/실행 경로 동기화 및 검증
- 사용자가 메인 데스크톱 폴더(`C:\Users\이홍원\Desktop\chzzk_downloader`)에서 도구를 실행하는 경우, 해당 경로의 `docs/UI_FEEDBACK_CATALOG.md`, `tools/preview_ui_feedbacks.py`, `src/chzzk_downloader/gui/feedback_showcase.py`를 일괄 동기화.
- 헤드리스 실행 검증:
  ```bash
  uv run --no-sync python -c "from chzzk_downloader.gui.feedback_showcase import FeedbackShowcaseWindow; from PyQt6.QtWidgets import QApplication; import sys; app = QApplication.instance() or QApplication(sys.argv); w = FeedbackShowcaseWindow(); print('Showcase verified!')"
  ```
