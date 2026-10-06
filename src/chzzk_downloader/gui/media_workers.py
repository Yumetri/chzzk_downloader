"""비동기 미디어 프로빙 및 무손실 리먹싱 워커 (R6 준수)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)


class MediaProbeWorker(QThread):
    """로컬 미디어 파일의 실제 재생 시간과 파일 크기를 비동기로 프로빙하는 경량 워커 (R6 준수)."""

    probed = pyqtSignal(str, float, int)  # (task_id, duration_seconds, file_size_bytes)
    failed = pyqtSignal(str, str)  # (task_id, error_message)

    def __init__(self, task_id: str, file_path: Path | str, parent: Any = None) -> None:
        super().__init__(parent)
        self.task_id = task_id
        self.file_path = Path(file_path)

    def run(self) -> None:
        try:
            from chzzk_downloader.core.ffmpeg_manager import probe_media_file

            meta = probe_media_file(self.file_path)
            dur = 0.0
            size = 0
            if isinstance(meta, dict):
                fmt = (
                    meta.get("format") if isinstance(meta.get("format"), dict) else meta
                )
                try:
                    dur = float(fmt.get("duration", 0.0))
                except (ValueError, TypeError):
                    dur = 0.0
                try:
                    size = int(fmt.get("size", 0))
                except (ValueError, TypeError):
                    size = 0

            if size <= 0 and self.file_path.exists():
                try:
                    size = self.file_path.stat().st_size
                except OSError:
                    pass
            self.probed.emit(self.task_id, dur, size)
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
            logger.debug("미디어 파일 프로빙 실패 (%s): %s", self.task_id, exc)
            self.failed.emit(self.task_id, str(exc))


class MediaRemuxWorker(QThread):
    """비정상 종료되거나 부분 다운로드된 미디어를 무손실 리먹싱하여 moov atom과 싱크를 정상화하는 워커 (R6 준수)."""

    remux_finished = pyqtSignal(str, bool, str)  # (task_id, success, output_path)

    def __init__(
        self,
        task_id: str,
        source_path: Path | str,
        target_path: Path | str,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.task_id = task_id
        self.source_path = Path(source_path)
        self.target_path = Path(target_path)

    def run(self) -> None:
        try:
            from chzzk_downloader.core.ffmpeg_manager import remux_media_file

            success = remux_media_file(self.source_path, self.target_path)
            self.remux_finished.emit(self.task_id, success, str(self.target_path))
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            logger.debug("미디어 무손실 리먹싱 실패 (%s): %s", self.task_id, exc)
            self.remux_finished.emit(self.task_id, False, str(self.source_path))
