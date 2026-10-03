---
name: desktop-sync
description: Use when the user asks to sync codebase changes (src, docs, tools, skills) from the worktree to the local desktop directory (C:\Users\이홍원\Desktop\chzzk_downloader).
---

# Desktop Sync (데스크톱 로컬 복사본 동기화 매뉴얼)

이 스킬은 Git 워크트리에서 개발된 최신 코드(`src/`), 규격 문서(`docs/`), 실행 도구(`tools/`), AI 스킬(`skills/`)을 사용자의 로컬 데스크톱 디렉터리(`C:\Users\이홍원\Desktop\chzzk_downloader`)로 안전하고 누락 없이 원클릭 복사 동기화하는 자동화 워크플로우입니다.

## 1. 동기화 대상 디렉터리

- `src/`: PyQt6 애플리케이션 및 다운로더 코어 패키지 전체
- `docs/`: UI 피드백 카탈로그, 적대적 검증 가이드, 기획 스펙 전체
- `tools/`: UI 피드백 프리뷰 실행 스크립트 (`preview_ui_feedbacks.py`)
- `.agents/skills/`: 에이전트 자동화 스킬 모음

## 2. 에이전트 실행 절차

사용자가 "데스크톱 동기화해줘", "바탕화면 복사해줘", "desktop-sync 실행" 등을 요청하면 아래 명령을 단독 실행합니다:

```bash
uv run --no-sync python .agents/skills/desktop-sync/scripts/sync.py
```

## 3. 동기화 후 검증

1. 스크립트 실행 결과에 모든 대상 디렉터리가 `✅ 동기화 완료`로 출력되었는지 확인합니다.
2. 사용자가 데스크톱 경로에서 UI 프리뷰 도구를 실행할 수 있음을 안내합니다:
   ```bash
   uv run python tools/preview_ui_feedbacks.py
   ```
