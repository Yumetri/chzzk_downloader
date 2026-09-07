"""UI 피드백(모달 & 토스트) 프리뷰 쇼케이스 실행 스크립트.

사용법:
    uv run python tools/preview_ui_feedbacks.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# src 디렉터리를 sys.path에 추가
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from chzzk_downloader.gui.feedback_showcase import main  # noqa: E402

if __name__ == "__main__":
    main()
