import glob
import time
import traceback
from pathlib import Path
from typing import Any, cast

from PyQt6.QtCore import QThread, pyqtSignal

from chzzk_downloader.core.task_models import TaskProgress, TaskSpec
from chzzk_downloader.core.ytdlp import (
    VodInfo,
    VodNotFoundError,
    YtDlpError,
    extract_vod_info,
)
from chzzk_downloader.core.ytdlp_opts import build_vod_download_opts
from chzzk_downloader.gui.section_poller import (
    SectionProgressPoller,
    format_eta,
    format_speed,
)


class DownloadCancelledError(Exception):
    """다운로드가 사용자에 의해 취소되었을 때 발생하는 내부 예외."""


class VodCheckWorker(QThread):
    """VOD 정보 비동기 조회를 위한 QThread 작업자 (yt-dlp 기반)."""

    finished_success = pyqtSignal(VodInfo)
    finished_failed = pyqtSignal(str)

    def __init__(self, video_target: str, parent=None) -> None:
        super().__init__(parent)
        self.video_target = video_target

    def run(self) -> None:
        """백그라운드 스레드에서 yt-dlp로 VOD 정보를 추출합니다."""
        url = (
            self.video_target
            if self.video_target.startswith("http")
            else f"https://chzzk.naver.com/video/{self.video_target}"
        )
        try:
            info = extract_vod_info(url)
            self.finished_success.emit(info)
        except VodNotFoundError as e:
            self.finished_failed.emit(str(e))
        except YtDlpError as e:
            self.finished_failed.emit(str(e))
        except Exception as e:
            self.finished_failed.emit(f"예기치 못한 오류: {e}")


class CookieVerifyWorker(QThread):
    """치지직 세션 유효성을 비동기로 검증하는 작업자."""

    finished_verification = pyqtSignal(object, str)

    def __init__(self, timeout: float = 3.0, parent=None) -> None:
        super().__init__(parent)
        self.timeout = timeout

    def run(self) -> None:
        from chzzk_downloader.core.cookie_manager import verify_cookie_session

        status, msg = verify_cookie_session(timeout=self.timeout)
        self.finished_verification.emit(status, msg)


class FFmpegBootstrapWorker(QThread):
    """FFmpeg 가용성 검증 및 백그라운드 자동 다운로드를 수행하는 비동기 작업자 (T0110)."""

    finished_bootstrap = pyqtSignal(bool, str)
    download_progress = pyqtSignal(int, int)

    def __init__(
        self,
        target_dir: str | None = None,
        download_url: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.target_dir = target_dir
        self.download_url = download_url
        self._is_cancelled = False

    def cancel(self) -> None:
        """다운로드 작업을 안전하게 취소 요청합니다."""
        self._is_cancelled = True

    def run(self) -> None:
        """백그라운드 스레드에서 FFmpeg 1~6단계 생명주기 및 온디맨드 다운로드를 수행합니다."""
        from chzzk_downloader.core.ffmpeg_manager import ensure_ffmpeg_available

        try:
            if self._is_cancelled:
                self.finished_bootstrap.emit(False, "다운로드가 취소되었습니다.")
                return

            ok, path = ensure_ffmpeg_available(
                auto_download=True,
                target_dir=self.target_dir,
                download_url=self.download_url,
                progress_callback=lambda cur, tot: self.download_progress.emit(
                    cur, tot
                ),
                cancel_check=lambda: self._is_cancelled,
            )

            if self._is_cancelled:
                self.finished_bootstrap.emit(False, "다운로드가 취소되었습니다.")
            elif ok and path:
                self.finished_bootstrap.emit(True, str(path))
            else:
                self.finished_bootstrap.emit(
                    False, "FFmpeg 바이너리를 준비하지 못했습니다."
                )
        except Exception as e:
            self.finished_bootstrap.emit(False, f"FFmpeg 준비 중 예외 발생: {e}")


class VodDownloadWorker(QThread):
    """백그라운드 스레드에서 VOD 다운로드를 실행하는 비동기 작업자 (T0111)."""

    progress_updated = pyqtSignal(TaskProgress)
    download_finished = pyqtSignal(str, str)  # (task_id, final_file_path)
    download_failed = pyqtSignal(str, str, str, str)  # (task_id, err_type, msg, tb)
    download_stopped = pyqtSignal(str)  # (task_id)

    def __init__(self, task_spec: TaskSpec, parent=None) -> None:
        super().__init__(parent)
        self.task_spec = task_spec
        self.task_id = task_spec.task_id
        self._is_cancelled = False
        self.created_paths: set[Path] = set()
        self._last_progress_emit_time = 0.0
        self._start_time = 0.0
        self._ydl_opts: dict[str, Any] = {}
        self._poller: SectionProgressPoller | None = None

    def cancel(self) -> None:
        """다운로드 작업을 안전하게 취소 요청합니다."""
        self._is_cancelled = True
        if self._poller is not None:
            self._poller.stop()

    @property
    def is_cancelled(self) -> bool:
        """취소 요청 여부를 반환합니다."""
        return self._is_cancelled

    def _progress_hook(self, d: dict[str, Any]) -> None:
        """yt-dlp 내부 진행 상태 콜백 (취소 감지 및 100ms 스로틀링 진행률 전달)."""
        tmp_name = d.get("tmpfilename")
        if tmp_name:
            self.created_paths.add(Path(tmp_name))
        file_name = d.get("filename")
        if file_name:
            self.created_paths.add(Path(file_name))

        if self._is_cancelled:
            raise DownloadCancelledError("다운로드가 사용자에 의해 취소되었습니다.")

        status = d.get("status")
        now_perf = time.perf_counter()
        elapsed = now_perf - self._start_time if self._start_time > 0 else 0.0

        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            pct = (downloaded / total * 100.0) if total > 0 else 0.0
            pct = min(100.0, max(0.0, pct))
            speed = float(d.get("speed") or 0.0)
            eta = int(d.get("eta") or 0)

            now = time.monotonic()
            if now - self._last_progress_emit_time >= 0.1:
                self._last_progress_emit_time = now
                progress = TaskProgress(
                    task_id=self.task_id,
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    percentage=round(pct, 1),
                    speed_bytes_sec=speed,
                    speed_str=format_speed(speed),
                    eta_seconds=eta,
                    eta_str=format_eta(eta),
                    elapsed_seconds=elapsed,
                )
                self.progress_updated.emit(progress)

        elif status == "finished":
            total = d.get("total_bytes") or d.get("downloaded_bytes") or 0
            progress = TaskProgress(
                task_id=self.task_id,
                downloaded_bytes=total,
                total_bytes=total,
                percentage=100.0,
                speed_bytes_sec=0.0,
                speed_str="0.0 KB/s",
                eta_seconds=0,
                eta_str="00:00:00",
                elapsed_seconds=elapsed,
            )
            self.progress_updated.emit(progress)

    def _cleanup_partial_files(self, delete_media: bool = True) -> None:
        """취소 또는 실패 시 생성된 파일들을 정리합니다. delete_media=False 시 유효한 미디어(> 0B)는 보존합니다."""
        target_path = Path(self.task_spec.save_path)
        temp_ytdl = Path(str(target_path) + ".ytdl")
        try:
            if temp_ytdl.is_file() and delete_media:
                temp_ytdl.unlink(missing_ok=True)
        except OSError:
            pass

        cleanup_targets = set(self.created_paths)
        cleanup_targets.add(Path(str(target_path) + ".part"))
        if delete_media:
            cleanup_targets.add(target_path)

        for p in cleanup_targets:
            try:
                if p.is_file() and (delete_media or p.stat().st_size == 0):
                    p.unlink(missing_ok=True)
            except OSError:
                pass

    def cleanup_partial_files(self, delete_media: bool = True) -> None:
        """취소 또는 실패 시 워커가 생성한 임시 파일들을 안전하게 정리합니다 (공개 메서드)."""
        self._cleanup_partial_files(delete_media=delete_media)

    def _resolve_final_path(self, target_path: Path) -> Path:
        """리먹싱 등으로 확장자가 변경되었을 가능성을 확인하여 최종 경로를 찾습니다."""
        if target_path.exists():
            return target_path
        escaped_stem = glob.escape(target_path.stem)
        candidates = list(target_path.parent.glob(f"{escaped_stem}.*"))
        valid = [
            c
            for c in candidates
            if not c.name.endswith(".part") and not c.name.endswith(".ytdl")
        ]
        return valid[0] if valid else target_path

    def run(self) -> None:
        """yt-dlp 인스턴스를 구동하여 비디오를 다운로드합니다."""
        import yt_dlp

        if self._is_cancelled:
            self.download_stopped.emit(self.task_id)
            return

        try:
            self._start_time = time.perf_counter()
            self._ydl_opts = build_vod_download_opts(self.task_spec)
            self._ydl_opts["progress_hooks"] = [self._progress_hook]

            is_section = (
                self.task_spec.section_start is not None
                or self.task_spec.section_end is not None
            )
            if is_section:
                self._poller = SectionProgressPoller(
                    task_id=self.task_id,
                    save_path=Path(self.task_spec.save_path),
                    progress_callback=self.progress_updated.emit,
                )
                self._poller.start()

            try:
                with yt_dlp.YoutubeDL(cast(Any, self._ydl_opts)) as ydl:
                    ydl.download([self.task_spec.video_url])
            finally:
                if self._poller is not None:
                    self._poller.stop()
                    self._poller = None

            if self._is_cancelled:
                self._cleanup_partial_files(delete_media=False)
                self.download_stopped.emit(self.task_id)
                return

            final_path = self._resolve_final_path(Path(self.task_spec.save_path))
            if not final_path.exists():
                raise FileNotFoundError(
                    f"다운로드 대상 파일이 디스크에 생성되지 않았습니다: {final_path}"
                )

            if final_path.stat().st_size <= 0:
                final_path.unlink(missing_ok=True)
                raise ValueError(
                    f"다운로드된 파일의 크기가 0바이트(빈 파일)입니다: {final_path}"
                )

            self.download_finished.emit(self.task_id, str(final_path))

        except DownloadCancelledError:
            self._cleanup_partial_files(delete_media=False)
            self.download_stopped.emit(self.task_id)
        except Exception as e:
            self._cleanup_partial_files(delete_media=False)
            if self._is_cancelled:
                self.download_stopped.emit(self.task_id)
            else:
                self.download_failed.emit(
                    self.task_id,
                    type(e).__name__,
                    str(e),
                    traceback.format_exc(),
                )
