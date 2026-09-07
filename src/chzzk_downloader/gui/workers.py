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
