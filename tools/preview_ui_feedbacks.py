"""UI 피드백(모달 M01~M11, 토스트 T01~T08, 작업 카드 C01~C09) 프리뷰 쇼케이스 실행 스크립트.

사용법:
    uv run python tools/preview_ui_feedbacks.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# 최신 작업 워크트리 및 로컬 src 경로 탐색 (우선순위 순서)
CANDIDATE_DIRS = [
    Path(__file__).resolve().parent.parent / "src",
    Path(r"C:\Users\이홍원\Desktop\chzzk_downloader\src"),
    Path(r"C:\Users\이홍원\Desktop\code_training\chzzk_downloader\src"),
]

for src_dir in CANDIDATE_DIRS:
    if src_dir.exists():
        src_str = str(src_dir.resolve())
        if src_str not in sys.path:
            sys.path.insert(0, src_str)
        break

from chzzk_downloader.gui.feedback_showcase import main  # noqa: E402

if __name__ == "__main__":
    main()
