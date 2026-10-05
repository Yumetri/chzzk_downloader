"""VOD 구간 다운로드 진행률 및 디스크 파일 크기 실시간 모니터링 폴러."""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from pathlib import Path

from chzzk_downloader.core.task_models import TaskProgress

logger = logging.getLogger(__name__)


def format_speed(speed: float) -> str:
    """초당 바이트 수를 속도 문자열로 변환합니다."""
    if math.isnan(speed) or math.isinf(speed) or speed <= 0:
        return "0.0 KB/s"
    if speed < 1024 * 1024:
        return f"{speed / 1024:.1f} KB/s"
    if speed < 1024 * 1024 * 1024:
        return f"{speed / (1024 * 1024):.1f} MB/s"
    return f"{speed / (1024 * 1024 * 1024):.1f} GB/s"


def format_eta(seconds: int) -> str:
    """초 단위 시간을 ETA 문자열(예: '00:03:25')로 변환합니다."""
    if seconds <= 0:
        return "00:00:00"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class SectionProgressPoller:
    """yt-dlp FFmpeg 구간 다운로드 중 디스크 파일 증가를 감시하여 실시간 진행률을 산출하는 비동기 폴러."""

    def __init__(
        self,
        task_id: str,
        save_path: Path,
        poll_interval_sec: float = 0.2,
        estimated_total_bytes: int = 0,
        progress_callback: Callable[[TaskProgress], None] | None = None,
    ) -> None:
        self.task_id = task_id
        self.save_path = Path(save_path)
        self.poll_interval_sec = max(0.02, float(poll_interval_sec))
        self.estimated_total_bytes = max(0, int(estimated_total_bytes))
        self.progress_callback = progress_callback

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_time: float = 0.0
        self._last_poll_time: float = 0.0
        self._last_bytes: int = 0

    def start(self) -> None:
        """폴링 스레드를 시작합니다."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._start_time = time.perf_counter()
        self._last_poll_time = self._start_time
        self._last_bytes = 0
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"SectionPoller-{self.task_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """폴링 스레드를 정지하고 종료를 대기합니다."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None

    def _get_current_file_size(self) -> int:
        """타깃 파일 또는 임시(.part) 파일의 현재 디스크 크기(바이트)를 반환합니다."""
        candidates = [
            self.save_path,
            Path(str(self.save_path) + ".part"),
            Path(str(self.save_path) + ".ytdl"),
        ]
        max_size = 0
        for p in candidates:
            try:
                if p.is_file():
                    s = p.stat().st_size
                    if s > max_size:
                        max_size = s
            except (OSError, ValueError):
                continue
        return max_size

    def _run_loop(self) -> None:
        """지정된 주기로 파일 크기를 검사하고 TaskProgress를 생성하여 전달합니다."""
        while not self._stop_event.wait(self.poll_interval_sec):
            now = time.perf_counter()
            cur_bytes = self._get_current_file_size()
            elapsed = now - self._start_time if self._start_time > 0 else 0.0
            delta_t = now - self._last_poll_time

            speed = 0.0
            if delta_t > 0:
                speed = max(0.0, float(cur_bytes - self._last_bytes) / delta_t)

            self._last_poll_time = now
            self._last_bytes = cur_bytes

            total_bytes = self.estimated_total_bytes
            pct = 0.0
            eta = 0
            if total_bytes > 0:
                pct = min(99.0, (cur_bytes / total_bytes) * 100.0)
                if speed > 0 and cur_bytes < total_bytes:
                    eta = int((total_bytes - cur_bytes) / speed)

            progress = TaskProgress(
                task_id=self.task_id,
                downloaded_bytes=cur_bytes,
                total_bytes=total_bytes,
                percentage=round(pct, 1),
                speed_bytes_sec=speed,
                speed_str=format_speed(speed),
                eta_seconds=eta,
                eta_str=format_eta(eta),
                elapsed_seconds=elapsed,
            )

            if self.progress_callback is not None:
                try:
                    self.progress_callback(progress)
                except (OSError, ValueError, RuntimeError) as exc:
                    logger.warning(
                        "진행률 콜백 전달 중 오류 발생 (task_id=%s): %s",
                        self.task_id,
                        exc,
                    )
