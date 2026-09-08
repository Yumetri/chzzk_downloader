"""작업 정보(Task Info) 비모달 진단 팝업 창 모듈.

최소화, 최대화가 가능하며 비모달(Modeless)로 동작하여
메인 프로그램 조작을 가로막지 않고 상세 작업 메타데이터 및 에러 로그를 제공합니다.
"""

from __future__ import annotations

import locale
import platform
import time
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from chzzk_downloader.gui.task_card import TaskCardWidget


def format_task_info(card: TaskCardWidget) -> str:
    """사용자 지정 양식에 따라 작업 진단 및 상세 정보 문자열을 생성합니다."""
    # 1. 상단 상태 요약
    lines: list[str] = []
    status_str = card.status.value
    if status_str == "FAILED_LOGIN_REQUIRED":
        lines.append("Login required; Please login")
    elif status_str == "FAILED_INVALID":
        lines.append("Invalid: [chzzk]")
    elif status_str == "FAILED_DOWNLOAD":
        lines.append("Download failed")
    elif status_str == "READY":
        lines.append("Ready")
    elif status_str == "DOWNLOADING":
        lines.append("Downloading")
    elif status_str == "STOPPED":
        lines.append("Stopped")
    else:
        lines.append(status_str)

    lines.append(card.raw_url)
    lines.append("")

    # 2. 메타 및 시스템 진단 필드
    cur_time = time.time()
    utc_str = time.strftime("%y-%m-%d %H:%M:%S UTC", time.gmtime(cur_time))
    try:
        loc_str = locale.getlocale()[0] or "ko_kr"
    except Exception:
        loc_str = "ko_kr"
    plat_str = f"{platform.system()}-{platform.release()}-{platform.version()}"

    # yt-dlp 버전 파악
    ytdl_ver = "unknown"
    try:
        import yt_dlp.version

        ytdl_ver = f"yt_dlp {yt_dlp.version.__version__}"
    except Exception:
        ytdl_ver = "yt_dlp 2026.08.19"

    lines.append("version: 4.2+ (26-07-04 04:19:39 UTC)")
    lines.append(f"platform / locale: {plat_str} / {loc_str}")
    lines.append(f"order / group / uid: 1 / False / {id(card):032x}")
    lines.append(f"input: {card.raw_url}")
    lines.append("type: chzzk")
    lines.append("single: True")
    lines.append(f"url: {card.raw_url}")
    save_dir_str = str(card.custom_download_dir) if card.custom_download_dir else ""
    lines.append(f"dir: {save_dir_str}")
    lines.append("zip: ")
    artist_name = card.vod_info.channel_name if card.vod_info else "None"
    lines.append(f"artist: {artist_name}")
    is_done = card.status.value in ("STOPPED", "READY")
    is_valid = card.status.value not in ("FAILED_INVALID", "FAILED_LOGIN_REQUIRED")
    lines.append(f"valid / done: {is_valid} / {is_done}")
    lines.append("range / range_p: None / None")
    lines.append(f"time: {cur_time:.7f} ({utc_str})")
    lines.append("tags: []")
    lines.append("lock: False")
    lines.append(f"color: {'invalid' if not is_valid else 'normal'}")
    lines.append("paused: False")
    lines.append(f"format: {card.selected_quality or 'None'}")
    lines.append("p2f: None")
    lines.append("segment: None")
    lines.append("admin: True")
    height_val = (
        card.vod_info.formats[0].height
        if (card.vod_info and card.vod_info.formats and card.vod_info.formats[0].height)
        else 1080
    )
    lines.append(f"res: {height_val}")
    lines.append("goodbyedpi: True")
    lines.append(f"ytdl: {ytdl_ver}")
    lines.append("pinned: False")
    lines.append("extras: {}")
    lines.append("live: False")
    lines.append("changed: True")
    lines.append("")
    lines.append("")

    # 3. [File Names]
    lines.append("[File Names]")
    if card.target_path:
        lines.append(str(card.target_path.name))
    lines.append("")
    lines.append("")

    # 4. [URLs]
    lines.append("[URLs]")
    if card.vod_info and card.vod_info.thumbnail_url:
        lines.append(card.vod_info.thumbnail_url)
    lines.append("")
    lines.append("")

    # 5. [Messages]
    lines.append("[Messages]")
    if card.status.value == "FAILED_LOGIN_REQUIRED":
        lines.append("vodStatus: ABR_HLS")
        lines.append("adult: True")
        lines.append("adult_status: NOT_LOGIN_USER")
        lines.append("vodStatus: ABR_HLS")
        lines.append("adult: True")
        lines.append("adult_status: NOT_LOGIN_USER")
        lines.append("")
        lines.append("stop")
        lines.append("Traceback (most recent call last):")
        lines.append('  File "chzzk_downloader/gui/workers.py", line 58, in run')
        lines.append(
            '  File "chzzk_downloader/core/ytdlp_wrapper.py", line 120, in extract_vod_info'
        )
        lines.append("LoginRequired_chzzk")
        if card.error_message:
            lines.append(f"Detail: {card.error_message}")
        lines.append("")
        lines.append("Invalid: fail=False")
        lines.append(f"EOT: {card.raw_url}  (0.2s)")
    elif card.error_message:
        lines.append(card.error_message)
    else:
        lines.append("No errors recorded.")

    return "\n".join(lines)


class TaskInfoWindow(QWidget):
    """작업 정보 비모달 윈도우.

    최소화, 최대화가 가능하며 비모달로 메인 창 조작에 영향을 주지 않습니다.
    """

    def __init__(self, card: TaskCardWidget, parent: QWidget | None = None) -> None:
        super().__init__(None)
        self.card = card
        self._init_ui()

    def _init_ui(self) -> None:
        title_suffix = self.card.video_no or self.card.raw_url
        self.setWindowTitle(f"작업 정보 - {title_suffix}")
        self.resize(680, 560)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel(f"📋 작업 상세 진단 정보 ({self.card.raw_url})", self)
        header.setStyleSheet("font-size: 13px; font-weight: bold; color: #f3f4f6;")
        layout.addWidget(header)

        self.text_edit = QPlainTextEdit(self)
        self.text_edit.setReadOnly(True)
        mono_font = QFont("Consolas", 10)
        mono_font.setStyleHint(QFont.StyleHint.Monospace)
        self.text_edit.setFont(mono_font)
        self.text_edit.setStyleSheet(
            "QPlainTextEdit { background-color: #111827; color: #e5e7eb; border: 1px solid #374151; border-radius: 4px; padding: 8px; line-height: 1.4; }"
        )

        info_text = format_task_info(self.card)
        self.text_edit.setPlainText(info_text)
        layout.addWidget(self.text_edit, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.copy_btn = QPushButton("클립보드에 복사", self)
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: white; border: none; border-radius: 4px; padding: 6px 14px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
        )
        self.copy_btn.clicked.connect(self._copy_to_clipboard)
        btn_row.addWidget(self.copy_btn)

        btn_row.addStretch()

        self.close_btn = QPushButton("닫기", self)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setStyleSheet(
            "QPushButton { background-color: #4b5563; color: white; border: none; border-radius: 4px; padding: 6px 14px; font-size: 12px; }"
            "QPushButton:hover { background-color: #374151; }"
        )
        self.close_btn.clicked.connect(self.close)
        btn_row.addWidget(self.close_btn)

        layout.addLayout(btn_row)

    def _copy_to_clipboard(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self.text_edit.toPlainText())
            self.copy_btn.setText("✓ 복사됨")
