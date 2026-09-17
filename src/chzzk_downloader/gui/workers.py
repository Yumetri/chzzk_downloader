"""비동기 백그라운드 작업자 모듈."""

from PyQt6.QtCore import QThread, pyqtSignal

from chzzk_downloader.core.ytdlp import (
    VodInfo,
    VodNotFoundError,
    YtDlpError,
    extract_vod_info,
)


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
                progress_callback=lambda cur, tot: self.download_progress.emit(cur, tot),
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
