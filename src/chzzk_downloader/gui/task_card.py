"""다운로드 작업 카드(Task Card) 위젯 모듈."""

import html
import urllib.request
from pathlib import Path
from typing import Any

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QContextMenuEvent,
    QCursor,
    QEnterEvent,
    QHideEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QShowEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from chzzk_downloader.config import AVAILABLE_EXTENSIONS, DEFAULT_USER_AGENT
from chzzk_downloader.core.filename_generator import (
    generate_vod_filename,
    resolve_duplicate_filename,
)
from chzzk_downloader.core.settings_manager import get_current_settings
from chzzk_downloader.core.task_models import TaskProgress, TaskSpec, TaskStatus
from chzzk_downloader.core.url_parser import parse_chzzk_vod_url
from chzzk_downloader.core.ytdlp import VodInfo
from chzzk_downloader.gui.dialogs import ask_confirm_dialog

_DETACHED_LOADERS: set[QThread] = set()
_DETACHED_PROBE_WORKERS: set[QThread] = set()


def _delete_file_safely(file_path: Path | None) -> bool:
    """Windows Shell 휴지통 이동 또는 unlink를 통한 안전한 파일 삭제 (재생 중 삭제 및 임시 .part 파일 정리 지원)."""
    if file_path is None:
        return False
    path_str = str(file_path).strip()
    if not path_str or path_str in (".", "/"):
        return False

    stem = file_path.stem.strip()
    if not stem:
        return False

    targets: list[Path] = []
    if file_path.is_file():
        targets.append(file_path)

    # yt-dlp 임시 파일 (.part, .ytdl 등) 정확한 타깃 경로만 추가 (이웃 파일 오삭제 방지)
    part_file = Path(str(file_path) + ".part")
    if part_file.is_file() and part_file not in targets:
        targets.append(part_file)
    ytdl_file = Path(str(file_path) + ".ytdl")
    if ytdl_file.is_file() and ytdl_file not in targets:
        targets.append(ytdl_file)

    if not targets:
        # 삭제할 본체 파일도, 임시 파일도 이미 디스크에 없음 (외부 선제 삭제 등 정리 완료)
        return True

    import sys

    success = True
    for target in targets:
        deleted = False
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                class SHFILEOPSTRUCTW(ctypes.Structure):
                    _fields_ = [
                        ("hwnd", wintypes.HWND),
                        ("wFunc", wintypes.UINT),
                        ("pFrom", wintypes.LPCWSTR),
                        ("pTo", wintypes.LPCWSTR),
                        ("fFlags", wintypes.WORD),
                        ("fAnyOperationsAborted", wintypes.BOOL),
                        ("hNameMappings", wintypes.LPVOID),
                        ("lpszProgressTitle", wintypes.LPCWSTR),
                    ]

                fo_delete = 3
                fof_allowundo = 0x0040
                fof_noconfirmation = 0x0010
                fof_silent = 0x0004
                fof_noerrorui = 0x0400

                p_from = str(target.resolve()) + "\0\0"
                file_op = SHFILEOPSTRUCTW(
                    hwnd=None,
                    wFunc=fo_delete,
                    pFrom=p_from,
                    pTo=None,
                    fFlags=fof_allowundo
                    | fof_noconfirmation
                    | fof_silent
                    | fof_noerrorui,
                    fAnyOperationsAborted=False,
                    hNameMappings=None,
                    lpszProgressTitle=None,
                )
                ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(file_op))
                if ret == 0 and not file_op.fAnyOperationsAborted:
                    deleted = True
            except Exception:
                pass

        if not deleted:
            import time

            for attempt in range(3):
                try:
                    target.unlink(missing_ok=True)
                    deleted = True
                    break
                except OSError:
                    if attempt < 2:
                        time.sleep(0.05)
            if not deleted:
                success = False

    return success


def match_default_quality(available_qualities: list[str], target_quality: str) -> str:
    """제공 가능한 화질 목록 중에서 설정의 기본 화질(target_quality)에 가장 적합한 화질을 찾습니다.

    - target_quality가 '최고 화질'이거나 비어있으면 목록의 0번(최고화질)을 반환합니다.
    - target_quality와 완전 일치하거나 접두사 일치(예: '720p' -> '720p60')하는 항목을 우선 반환합니다.
    - 일치 항목이 없으면 목표 해상도 이하 중 가장 큰 화질을 반환합니다.
    - 그 외에는 목록의 0번(최고화질)으로 폴백합니다.
    """
    if not available_qualities:
        return ""
    if not target_quality or target_quality == "최고 화질":
        return available_qualities[0]

    # 1. 완전 일치
    if target_quality in available_qualities:
        return target_quality

    # 2. 접두사 일치 (예: "720p" -> "720p60")
    for q in available_qualities:
        if q.startswith(target_quality):
            return q

    # 3. 목표 해상도(height) 이하 중 최고 화질
    try:
        target_digits = "".join(c for c in target_quality if c.isdigit())
        if target_digits:
            target_h = int(target_digits)
            for q in available_qualities:
                h_digits = "".join(c for c in q.split("p")[0] if c.isdigit())
                if h_digits and int(h_digits) <= target_h:
                    return q
    except ValueError:
        pass

    return available_qualities[0]


class SpinnerWidget(QWidget):
    """버퍼링 회전 인디케이터 위젯."""

    def __init__(
        self,
        size: int = 14,
        color: str = "#3b82f6",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._size = size
        self._color = color
        self.setFixedSize(size, size)
        self._angle = 0
        self._was_running = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)

    def _rotate(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def start(self) -> None:
        self._was_running = True
        if not self._timer.isActive():
            self._timer.start(50)

    def stop(self) -> None:
        self._was_running = False
        if self._timer.isActive():
            self._timer.stop()
        self._angle = 0
        self.update()

    def paintEvent(self, event: QPaintEvent | None) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(self._color), 2)
        painter.setPen(pen)
        painter.translate(self._size / 2, self._size / 2)
        painter.rotate(self._angle)
        span = 270 * 16
        r = (self._size - 3) / 2
        painter.drawArc(int(-r), int(-r), int(2 * r), int(2 * r), 0, span)

    def hideEvent(self, event: QHideEvent | None) -> None:  # noqa: N802
        # 위젯 가시성이 숨겨질 때 CPU 낭비 방지를 위해 타이머만 일시 정지 (동작 의도 _was_running은 유지)
        if self._timer.isActive():
            self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event: QShowEvent | None) -> None:  # noqa: N802
        # 위젯이 다시 화면에 노출될 때 이전 동작 중이었으면 타이머를 대칭적으로 재개
        if getattr(self, "_was_running", False) and not self._timer.isActive():
            self._timer.start(50)
        super().showEvent(event)


def format_duration(seconds: int) -> str:
    """초 단위 재생 시간을 'MM:SS' 또는 'HH:MM:SS' 형식으로 포맷팅합니다."""
    if seconds <= 0:
        return "00:00"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class ThumbnailLoaderThread(QThread):
    """썸네일 이미지 비동기 다운로드 스레드."""

    loaded = pyqtSignal(bytes)

    def __init__(self, url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.url = url

    def run(self) -> None:
        try:
            req = urllib.request.Request(
                self.url,
                headers={"User-Agent": DEFAULT_USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                data = response.read()
                self.loaded.emit(data)
        except Exception:
            pass


class TaskCardWidget(QFrame):
    """작업 목록의 단일 작업 카드 위젯.

    4분면 레이아웃:
    - 1번 위치 (좌상단): 작업명 / 제목 라벨
    - 2번 위치 (우상단): 회색조 액션 아이콘 (삭제 ✕)
    - 3번 위치 (우하단): 재생 시간, 화질, 진행/실패 상태 라벨
    - 4번 위치 (좌하단): 인증/대기/다운로드 중 상태별 인터랙션 컨테이너
    """

    delete_requested = pyqtSignal()
    request_open_cookies = pyqtSignal()
    request_naver_login = pyqtSignal()
    download_started = pyqtSignal()
    download_stopped = pyqtSignal()
    download_blocked = pyqtSignal(str)
    request_start_download = pyqtSignal(object)  # (TaskSpec)
    request_stop_download = pyqtSignal(str)  # (task_id)
    retry_requested = pyqtSignal(str)  # (task_id)
    complete_requested = pyqtSignal(str)  # (task_id)

    def __init__(
        self,
        raw_url: str,
        status: TaskStatus = TaskStatus.ANALYZING,
        vod_info: VodInfo | None = None,
        video_no: str = "",
        task_id: str | None = None,
        is_live: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.raw_url = raw_url
        self.status = status
        self.vod_info = vod_info
        self.is_live = is_live
        if vod_info and hasattr(vod_info, "is_live") and vod_info.is_live:
            self.is_live = True
        self.video_no = (
            video_no
            or (vod_info.video_no if vod_info else "")
            or (parse_chzzk_vod_url(raw_url) or "")
        )
        self.task_id = task_id or self.video_no or self.raw_url
        self.waiting_position: int = 0
        self.error_message: str = ""
        self.error_type: str = ""
        self.traceback_str: str = ""
        self.final_file_path: Path | None = None
        self.is_deleted: bool = False
        self._has_started_download: bool = status == TaskStatus.DOWNLOADING
        self._stopped_without_file: bool = False
        self._stopped_duration_str: str | None = None
        self._is_stopped: bool = False
        self._applied_section_start: float | None = None
        self._applied_section_end: float | None = None
        self._probe_worker: Any = None
        self._thumb_loader: ThumbnailLoaderThread | None = None
        self._info_win: Any = None
        self.section_popup: Any = None

        self.custom_download_dir: Path | None = None
        self.target_path: Path | None = None
        self.selected_quality: str = ""
        self.last_progress: TaskProgress | None = None

        self._init_ui()
        if self.vod_info:
            self._populate_qualities()
        self._update_display()
        self._apply_style()

        if self.vod_info and self.vod_info.thumbnail_url:
            self._load_thumbnail(self.vod_info.thumbnail_url)

    @property
    def is_section_download(self) -> bool:
        """구간 다운로드가 설정된 작업인지 여부를 반환합니다."""
        if (
            self._applied_section_start is not None
            or self._applied_section_end is not None
        ):
            return True
        if self.section_popup is not None:
            s_start, s_end = self.section_popup.get_section_range()
            if s_start is not None or s_end is not None:
                return True
        return False

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(400, 88)

    def _init_ui(self) -> None:
        self.setObjectName("TaskCardWidget")
        self.setMinimumHeight(88)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(12)

        # 좌측: 썸네일 박스 (120x68px, 16:9) 및 회색 회전 위젯
        self.thumb_container = QWidget(self)
        self.thumb_container.setFixedSize(120, 68)
        self.thumb_container.setStyleSheet(
            "background-color: #2a2a2a; border-radius: 4px;"
        )
        thumb_grid = QGridLayout(self.thumb_container)
        thumb_grid.setContentsMargins(0, 0, 0, 0)
        thumb_grid.setSpacing(0)

        self.thumb_label = QLabel(self.thumb_container)
        self.thumb_label.setFixedSize(120, 68)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setScaledContents(True)
        self.thumb_label.setStyleSheet(
            "background-color: transparent; color: #888888; border-radius: 4px; font-weight: bold; font-size: 12px;"
        )
        self.thumb_label.setText("VOD")
        thumb_grid.addWidget(self.thumb_label, 0, 0)

        # 읽는 중(ANALYZING) 상태에서 빈 화면 중앙에 표시되는 회색 회전 위젯
        self.thumb_spinner = SpinnerWidget(
            size=24, color="#9ca3af", parent=self.thumb_container
        )
        self.thumb_spinner.hide()
        thumb_grid.addWidget(self.thumb_spinner, 0, 0, Qt.AlignmentFlag.AlignCenter)

        main_layout.addWidget(self.thumb_container)

        # 우측: 4분면 정보 영역
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 2, 0, 2)
        info_layout.setSpacing(4)

        # 상단 행: 1번 위치(좌상단 타이틀) + 2번 위치(우상단 액션 아이콘)
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(4)

        # 1번 위치 (좌상단): 작업명 / 상태 표시 라벨 (좌측 정렬 줄바꿈 지원)
        self.title_label = QLabel(self)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.title_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        top_row.addWidget(self.title_label, stretch=1)

        # 2-1. 폴더 열기(📁) 버튼
        self.open_folder_btn = QPushButton("📁", self)
        self.open_folder_btn.setToolTip("폴더 열기")
        self.open_folder_btn.setFixedSize(24, 24)
        self.open_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_folder_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #888888; border: none; font-size: 13px; }"
            "QPushButton:hover { background-color: rgba(255, 255, 255, 0.15); color: white; border-radius: 3px; }"
        )
        self.open_folder_btn.clicked.connect(self.open_folder)
        self.open_folder_btn.hide()
        top_row.addWidget(self.open_folder_btn)

        # 2-2. 파일 재생(▶) 버튼
        self.play_btn = QPushButton("▶", self)
        self.play_btn.setToolTip("재생")
        self.play_btn.setFixedSize(24, 24)
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #00ffa3; border: none; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: rgba(0, 255, 163, 0.2); border-radius: 3px; }"
        )
        self.play_btn.clicked.connect(self.play_media)
        self.play_btn.hide()
        top_row.addWidget(self.play_btn)

        # 2-3. 다시 시작(🔄) 버튼 (STOPPED, FAILED_DOWNLOAD 상태에서 활성화)
        self.retry_btn = QPushButton("🔄", self)
        self.retry_btn.setToolTip("다시 시작")
        self.retry_btn.setFixedSize(24, 24)
        self.retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #888888; border: none; font-size: 13px; }"
            "QPushButton:hover { background-color: rgba(0, 255, 163, 0.2); color: #00ffa3; border-radius: 3px; }"
        )
        self.retry_btn.clicked.connect(self._on_retry_clicked)
        self.retry_btn.hide()
        top_row.addWidget(self.retry_btn)

        # 2-4. 파일 삭제(🗑️) 버튼 (M11 모달 연동 및 안전 삭제)
        self.action_delete_file_btn = QPushButton("🗑️", self)
        self.action_delete_file_btn.setToolTip("파일 삭제")
        self.action_delete_file_btn.setFixedSize(24, 24)
        self.action_delete_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_delete_file_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #888888; border: none; font-size: 13px; }"
            "QPushButton:hover { background-color: rgba(239, 68, 68, 0.2); color: #ef4444; border-radius: 3px; }"
        )
        self.action_delete_file_btn.clicked.connect(self._on_delete_file_clicked)
        self.action_delete_file_btn.hide()
        top_row.addWidget(self.action_delete_file_btn)

        # 2-4. 삭제(✕) 버튼
        self.delete_btn = QPushButton("✕", self)
        self.delete_btn.setToolTip("목록에서 제거")
        self.delete_btn.setFixedSize(24, 24)
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sp = self.delete_btn.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self.delete_btn.setSizePolicy(sp)
        self.delete_btn.hide()
        self.delete_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #888888; border: none; font-size: 13px; font-weight: bold; }"
            "QPushButton:hover { background-color: rgba(239, 68, 68, 0.2); color: #ef4444; border-radius: 3px; }"
        )
        self.delete_btn.clicked.connect(self.delete_requested.emit)
        top_row.addWidget(self.delete_btn)

        info_layout.addLayout(top_row)
        info_layout.addStretch()

        # 하단 행: 4번 위치(좌하단 컨트롤) + 3번 위치(우하단 상태 요약)
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(8)

        # 4번 위치 (좌하단): 인증/대기/다운로드 중 상태별 인터랙션 컨테이너
        self.action_container = QWidget(self)
        action_layout = QHBoxLayout(self.action_container)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(6)

        # 4-1. 실패/오류/인증 필요 컨테이너 ([치지직 뱃지] [🗨️! 에러상세] [🍪] [N])
        self.auth_container = QWidget(self.action_container)
        auth_layout = QHBoxLayout(self.auth_container)
        auth_layout.setContentsMargins(0, 0, 0, 0)
        auth_layout.setSpacing(6)

        # 치지직 플랫폼 뱃지 (클릭 시 확인/취소 모달 후 해당 URL 브라우저 이동, 툴팁 없음)
        self.chzzk_badge = QPushButton("Z", self.auth_container)
        self.chzzk_badge.setFixedSize(24, 22)
        self.chzzk_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chzzk_badge.setStyleSheet(
            "QPushButton { background-color: #000000; color: #00ffa3; border: none; border-radius: 3px; font-weight: 900; font-size: 11px; padding: 0; }"
            "QPushButton:hover { background-color: #1f2937; }"
        )
        self.chzzk_badge.clicked.connect(self._on_chzzk_badge_clicked)

        # 말풍선 에러 상세 툴팁 버튼 (툴팁 "작업 정보", 클릭 시 비모달 진단 팝업 오픈)
        self.error_info_btn = QPushButton("🗨️!", self.auth_container)
        self.error_info_btn.setFixedSize(24, 22)
        self.error_info_btn.setToolTip("작업 정보")
        self.error_info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.error_info_btn.setStyleSheet(
            "QPushButton { background-color: #374151; color: #d1d5db; border: none; border-radius: 3px; font-weight: bold; font-size: 11px; padding: 0; }"
            "QPushButton:hover { background-color: #4b5563; color: white; }"
        )
        self.error_info_btn.clicked.connect(self.open_task_info_window)

        self.cookie_btn = QPushButton("🍪", self.auth_container)
        self.cookie_btn.setFixedSize(24, 22)
        self.cookie_btn.setToolTip("쿠키 설정")
        self.cookie_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cookie_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none; font-size: 14px; padding: 0; }"
            "QPushButton:hover { background-color: rgba(255, 255, 255, 0.15); border-radius: 3px; }"
        )
        self.login_btn = QPushButton("N", self.auth_container)
        self.login_btn.setFixedSize(24, 22)
        self.login_btn.setToolTip("네이버 로그인")
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.setStyleSheet(
            "QPushButton { background-color: #03c75a; color: white; border: none; border-radius: 3px; font-size: 12px; font-weight: 900; }"
            "QPushButton:hover { background-color: #02b150; }"
        )
        self.cookie_btn.clicked.connect(self.request_open_cookies.emit)
        self.login_btn.clicked.connect(self.request_naver_login.emit)

        self.failed_retry_btn = QPushButton("🔄", self.auth_container)
        self.failed_retry_btn.setToolTip("다시 시작")
        self.failed_retry_btn.setFixedSize(24, 22)
        self.failed_retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.failed_retry_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #888888; border: none; font-size: 13px; }"
            "QPushButton:hover { background-color: rgba(0, 255, 163, 0.2); color: #00ffa3; border-radius: 3px; }"
        )
        self.failed_retry_btn.clicked.connect(self._on_retry_clicked)
        self.failed_retry_btn.hide()

        self.failed_complete_btn = QPushButton("✓", self.auth_container)
        self.failed_complete_btn.setToolTip("완료")
        self.failed_complete_btn.setFixedSize(24, 22)
        self.failed_complete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.failed_complete_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #10b981; border: none; font-size: 13px; font-weight: bold; }"
            "QPushButton:hover { background-color: rgba(16, 185, 129, 0.2); border-radius: 3px; }"
        )
        self.failed_complete_btn.clicked.connect(self._on_complete_clicked)
        self.failed_complete_btn.hide()

        auth_layout.addWidget(self.chzzk_badge)
        auth_layout.addWidget(self.error_info_btn)
        auth_layout.addWidget(self.cookie_btn)
        auth_layout.addWidget(self.login_btn)
        auth_layout.addWidget(self.failed_retry_btn)
        auth_layout.addWidget(self.failed_complete_btn)
        self.auth_container.hide()

        # 4-2. 다운로드 대기 컨테이너 ([최고화질 드롭다운] [기본 확장자] [📁] [▶])
        self.ready_container = QWidget(self.action_container)
        ready_layout = QHBoxLayout(self.ready_container)
        ready_layout.setContentsMargins(0, 0, 0, 0)
        ready_layout.setSpacing(6)

        self.quality_combo = QComboBox(self.ready_container)
        self.quality_combo.setFixedHeight(22)
        self.quality_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quality_combo.setStyleSheet(
            "QComboBox { background-color: #2a2a2a; color: #f3f4f6; border: 1px solid #4b5563; border-radius: 3px; padding: 1px 6px; font-size: 11px; }"
            "QComboBox::drop-down { border: none; width: 14px; }"
            "QComboBox QAbstractItemView { background-color: #1e1e1e; color: #f3f4f6; selection-background-color: #3b82f6; border: 1px solid #4b5563; outline: none; }"
        )
        self.quality_combo.currentTextChanged.connect(self._on_quality_selected)

        self.ext_combo = QComboBox(self.ready_container)
        self.ext_combo.setFixedHeight(22)
        self.ext_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ext_combo.setStyleSheet(
            "QComboBox { background-color: #2a2a2a; color: #f3f4f6; border: 1px solid #4b5563; border-radius: 3px; padding: 1px 4px; font-size: 11px; }"
            "QComboBox::drop-down { border: none; width: 14px; }"
            "QComboBox QAbstractItemView { background-color: #1e1e1e; color: #f3f4f6; selection-background-color: #3b82f6; border: 1px solid #4b5563; outline: none; }"
        )
        self.ext_combo.addItems(list(AVAILABLE_EXTENSIONS))
        settings = get_current_settings()
        if settings.file_extension in AVAILABLE_EXTENSIONS:
            self.ext_combo.setCurrentText(settings.file_extension)

        self.folder_btn = QPushButton("📁", self.ready_container)
        self.folder_btn.setToolTip("저장 폴더 변경")
        self.folder_btn.setFixedSize(22, 22)
        self.folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; font-size: 12px; }"
            "QPushButton:hover { background-color: #374151; border-radius: 3px; }"
        )
        self.folder_btn.clicked.connect(self._on_change_folder_clicked)

        self.start_btn = QPushButton("▶", self.ready_container)
        self.start_btn.setToolTip("다운로드 시작")
        self.start_btn.setFixedSize(22, 22)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #3b82f6; border: none; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: rgba(59, 130, 246, 0.2); border-radius: 3px; }"
        )
        self.start_btn.clicked.connect(self.trigger_start_download)

        self.section_btn = QPushButton("구간 설정", self.ready_container)
        self.section_btn.setToolTip(
            "구간 설정 (키프레임 위치에 따라 수 초 오차가 발생할 수 있습니다)"
        )
        self.section_btn.setFixedHeight(22)
        self.section_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.section_btn.setStyleSheet(
            "QPushButton { background-color: #2a2a2a; color: #f3f4f6; border: 1px solid #4b5563; border-radius: 3px; padding: 1px 6px; font-size: 11px; }"
            "QPushButton:hover { background-color: #374151; }"
        )
        self.section_btn.clicked.connect(self._on_section_btn_clicked)

        from chzzk_downloader.gui.section_popup import SectionPopup

        self.section_popup = SectionPopup(self)
        self.section_popup.section_changed.connect(self._on_section_validity_changed)

        ready_layout.addWidget(self.quality_combo)
        ready_layout.addWidget(self.ext_combo)
        ready_layout.addWidget(self.section_btn)
        ready_layout.addWidget(self.folder_btn)
        ready_layout.addWidget(self.start_btn)
        self.ready_container.hide()

        # 4-3. VOD 다운로드 실행 중 컨테이너 ([Z] 뱃지 + [■] 중지 + 미니멀 프로그레스바 + 정수%)
        self.vod_downloading_container = QWidget(self.action_container)
        vod_downloading_layout = QHBoxLayout(self.vod_downloading_container)
        vod_downloading_layout.setContentsMargins(0, 0, 0, 0)
        vod_downloading_layout.setSpacing(6)

        self.vod_chzzk_badge = QPushButton("Z", self.vod_downloading_container)
        self.vod_chzzk_badge.setFixedSize(24, 22)
        self.vod_chzzk_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.vod_chzzk_badge.setStyleSheet(
            "QPushButton { background-color: #000000; color: #00ffa3; border: none; border-radius: 3px; font-weight: 900; font-size: 11px; padding: 0; }"
            "QPushButton:hover { background-color: #1f2937; }"
        )
        self.vod_chzzk_badge.clicked.connect(self._on_chzzk_badge_clicked)

        self.stop_btn = QPushButton("■", self.vod_downloading_container)
        self.stop_btn.setToolTip("다운로드 중지")
        self.stop_btn.setFixedSize(22, 22)
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #ef4444; border: none; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background-color: #374151; color: #f87171; border-radius: 4px; }"
        )
        self.stop_btn.clicked.connect(self.trigger_stop_download)

        self.progress_bar = QProgressBar(self.vod_downloading_container)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setMinimumWidth(100)
        self.progress_bar.setMaximumWidth(160)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: #2a2a2a; border: none; border-radius: 3px; }"
            "QProgressBar::chunk { background-color: #3b82f6; border-radius: 3px; }"
        )

        self.progress_bar.installEventFilter(self)

        self.pct_label = QLabel("0%", self.vod_downloading_container)
        self.pct_label.setStyleSheet(
            "color: #d1d5db; font-size: 11px; min-width: 24px;"
        )
        self.pct_label.installEventFilter(self)

        vod_downloading_layout.addWidget(self.vod_chzzk_badge)
        vod_downloading_layout.addWidget(self.stop_btn)
        vod_downloading_layout.addWidget(self.progress_bar)
        vod_downloading_layout.addWidget(self.pct_label)
        self.vod_downloading_container.hide()

        # 4-4. 라이브 녹화 중 컨테이너 ([Z] 뱃지 + [📺▶] 아이콘 + 녹화 중... + [■] 중지)
        self.live_recording_container = QWidget(self.action_container)
        live_layout = QHBoxLayout(self.live_recording_container)
        live_layout.setContentsMargins(0, 0, 0, 0)
        live_layout.setSpacing(6)

        self.live_chzzk_badge = QPushButton("Z", self.live_recording_container)
        self.live_chzzk_badge.setFixedSize(24, 22)
        self.live_chzzk_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.live_chzzk_badge.setStyleSheet(
            "QPushButton { background-color: #000000; color: #00ffa3; border: none; border-radius: 3px; font-weight: 900; font-size: 11px; padding: 0; }"
            "QPushButton:hover { background-color: #1f2937; }"
        )
        self.live_chzzk_badge.clicked.connect(self._on_chzzk_badge_clicked)

        self.live_icon_label = QLabel("📺▶", self.live_recording_container)
        self.live_icon_label.setStyleSheet(
            "color: #9ca3af; font-size: 12px; font-weight: bold;"
        )

        self.recording_label = QLabel("녹화 중…", self.live_recording_container)
        self.recording_label.setStyleSheet(
            "color: #ef4444; font-size: 11px; font-weight: 600;"
        )

        self.spinner = SpinnerWidget(size=14, parent=self.live_recording_container)

        self.live_stop_btn = QPushButton("■", self.live_recording_container)
        self.live_stop_btn.setToolTip("녹화 중지")
        self.live_stop_btn.setFixedSize(22, 22)
        self.live_stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.live_stop_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #ef4444; border: none; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background-color: #374151; color: #f87171; border-radius: 4px; }"
        )
        self.live_stop_btn.clicked.connect(self.trigger_stop_download)

        live_layout.addWidget(self.live_chzzk_badge)
        live_layout.addWidget(self.live_icon_label)
        live_layout.addWidget(self.recording_label)
        live_layout.addWidget(self.spinner)
        live_layout.addWidget(self.live_stop_btn)
        self.live_recording_container.hide()

        # 4-5. 완료 상태 컨테이너 (VOD 완료 시 [Z] 단독, Live 완료 시 [Z] [📺▶])
        self.completed_container = QWidget(self.action_container)
        completed_layout = QHBoxLayout(self.completed_container)
        completed_layout.setContentsMargins(0, 0, 0, 0)
        completed_layout.setSpacing(6)

        self.completed_chzzk_badge = QPushButton("Z", self.completed_container)
        self.completed_chzzk_badge.setFixedSize(24, 22)
        self.completed_chzzk_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.completed_chzzk_badge.setStyleSheet(
            "QPushButton { background-color: #000000; color: #00ffa3; border: none; border-radius: 3px; font-weight: 900; font-size: 11px; padding: 0; }"
            "QPushButton:hover { background-color: #1f2937; }"
        )
        self.completed_chzzk_badge.clicked.connect(self._on_chzzk_badge_clicked)

        self.completed_live_icon_label = QLabel("📺▶", self.completed_container)
        self.completed_live_icon_label.setStyleSheet(
            "color: #9ca3af; font-size: 12px; font-weight: bold;"
        )

        completed_layout.addWidget(self.completed_chzzk_badge)
        completed_layout.addWidget(self.completed_live_icon_label)
        self.completed_container.hide()

        # 4-6. 중단 상태 컨테이너 ([Z] 뱃지 + [🔄] 다시 시작 + [✓] 완료 확정 + 멈춘 프로그레스바 + {N}%)
        self.stopped_container = QWidget(self.action_container)
        stopped_layout = QHBoxLayout(self.stopped_container)
        stopped_layout.setContentsMargins(0, 0, 0, 0)
        stopped_layout.setSpacing(6)

        self.stopped_chzzk_badge = QPushButton("Z", self.stopped_container)
        self.stopped_chzzk_badge.setFixedSize(24, 22)
        self.stopped_chzzk_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stopped_chzzk_badge.setStyleSheet(
            "QPushButton { background-color: #000000; color: #00ffa3; border: none; border-radius: 3px; font-weight: 900; font-size: 11px; padding: 0; }"
            "QPushButton:hover { background-color: #1f2937; }"
        )
        self.stopped_chzzk_badge.clicked.connect(self._on_chzzk_badge_clicked)

        self.stopped_retry_btn = QPushButton("🔄", self.stopped_container)
        self.stopped_retry_btn.setToolTip("다시 시작")
        self.stopped_retry_btn.setFixedSize(24, 22)
        self.stopped_retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stopped_retry_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #888888; border: none; font-size: 13px; }"
            "QPushButton:hover { background-color: rgba(0, 255, 163, 0.2); color: #00ffa3; border-radius: 3px; }"
        )
        self.stopped_retry_btn.clicked.connect(self._on_retry_clicked)

        self.stopped_complete_btn = QPushButton("✓", self.stopped_container)
        self.stopped_complete_btn.setToolTip("완료")
        self.stopped_complete_btn.setFixedSize(24, 22)
        self.stopped_complete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stopped_complete_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #10b981; border: none; font-size: 13px; font-weight: bold; }"
            "QPushButton:hover { background-color: rgba(16, 185, 129, 0.2); border-radius: 3px; }"
        )
        self.stopped_complete_btn.clicked.connect(self._on_complete_clicked)

        self.stopped_progress_bar = QProgressBar(self.stopped_container)
        self.stopped_progress_bar.setFixedHeight(8)
        self.stopped_progress_bar.setMinimumWidth(80)
        self.stopped_progress_bar.setMaximumWidth(140)
        self.stopped_progress_bar.setRange(0, 100)
        self.stopped_progress_bar.setValue(0)
        self.stopped_progress_bar.setTextVisible(False)
        self.stopped_progress_bar.setStyleSheet(
            "QProgressBar { background-color: #2a2a2a; border: none; border-radius: 3px; }"
            "QProgressBar::chunk { background-color: #64748b; border-radius: 3px; }"
        )

        self.stopped_pct_label = QLabel("0%", self.stopped_container)
        self.stopped_pct_label.setStyleSheet(
            "color: #94a3b8; font-size: 11px; min-width: 24px;"
        )

        stopped_layout.addWidget(self.stopped_chzzk_badge)
        stopped_layout.addWidget(self.stopped_retry_btn)
        stopped_layout.addWidget(self.stopped_complete_btn)
        stopped_layout.addWidget(self.stopped_progress_bar)
        stopped_layout.addWidget(self.stopped_pct_label)
        self.stopped_container.hide()

        # 하위 호환용 별칭
        self.downloading_container = self.vod_downloading_container

        action_layout.addWidget(self.auth_container)
        action_layout.addWidget(self.ready_container)
        action_layout.addWidget(self.vod_downloading_container)
        action_layout.addWidget(self.live_recording_container)
        action_layout.addWidget(self.completed_container)
        action_layout.addWidget(self.stopped_container)

        bottom_row.addWidget(self.action_container)
        bottom_row.addStretch()

        # 3번 위치 (우하단): 실시간 다운로드 메트릭 컨테이너 (Hitomi 스타일)
        self.downloading_metrics_widget = QWidget(self)
        metrics_parent_layout = QHBoxLayout(self.downloading_metrics_widget)
        metrics_parent_layout.setContentsMargins(0, 0, 0, 0)
        metrics_parent_layout.setSpacing(0)

        # 3-1. VOD 다운로드 메트릭: [속도] | [남은 시간] | [⬇ 용량] (남은 시간 유무에 따라 속도만 이동, 용량 우측 끝 고정)
        self.vod_metrics_widget = QWidget(self.downloading_metrics_widget)
        vod_m_layout = QHBoxLayout(self.vod_metrics_widget)
        vod_m_layout.setContentsMargins(0, 0, 0, 0)
        vod_m_layout.setSpacing(4)
        vod_m_layout.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.speed_label = QLabel("", self.vod_metrics_widget)
        self.speed_label.setStyleSheet("color: #9ca3af; font-size: 11px;")

        self.eta_sep_label = QLabel("|", self.vod_metrics_widget)
        self.eta_sep_label.setStyleSheet("color: #4b5563; font-size: 11px;")

        self.eta_label = QLabel("", self.vod_metrics_widget)
        self.eta_label.setStyleSheet("color: #9ca3af; font-size: 11px;")

        self.size_sep_label = QLabel("|", self.vod_metrics_widget)
        self.size_sep_label.setStyleSheet("color: #4b5563; font-size: 11px;")

        self.size_label = QLabel("", self.vod_metrics_widget)
        self.size_label.setStyleSheet("color: #9ca3af; font-size: 11px;")

        vod_m_layout.addWidget(self.speed_label)
        vod_m_layout.addWidget(self.eta_sep_label)
        vod_m_layout.addWidget(self.eta_label)
        vod_m_layout.addWidget(self.size_sep_label)
        vod_m_layout.addWidget(self.size_label)

        # 3-2. Live 녹화 중 및 완료 상태 메트릭: 🕒 {시간}   ⬇ {용량} (Hitomi 사진 1, 2 규격)
        self.icon_metrics_widget = QWidget(self.downloading_metrics_widget)
        icon_m_layout = QHBoxLayout(self.icon_metrics_widget)
        icon_m_layout.setContentsMargins(0, 0, 0, 0)
        icon_m_layout.setSpacing(4)
        icon_m_layout.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.clock_icon_label = QLabel("🕒", self.icon_metrics_widget)
        self.clock_icon_label.setStyleSheet("color: #9ca3af; font-size: 11px;")

        self.time_metric_label = QLabel("", self.icon_metrics_widget)
        self.time_metric_label.setStyleSheet("color: #9ca3af; font-size: 11px;")

        self.spacer_label = QLabel("  ", self.icon_metrics_widget)
        self.spacer_label.setStyleSheet("font-size: 11px;")

        self.arrow_icon_label = QLabel("⬇", self.icon_metrics_widget)
        self.arrow_icon_label.setStyleSheet("color: #9ca3af; font-size: 11px;")

        self.size_metric_label = QLabel("", self.icon_metrics_widget)
        self.size_metric_label.setStyleSheet("color: #9ca3af; font-size: 11px;")

        icon_m_layout.addWidget(self.clock_icon_label)
        icon_m_layout.addWidget(self.time_metric_label)
        icon_m_layout.addWidget(self.spacer_label)
        icon_m_layout.addWidget(self.arrow_icon_label)
        icon_m_layout.addWidget(self.size_metric_label)

        self.elapsed_label = self.time_metric_label  # 호환용 별칭

        metrics_parent_layout.addWidget(self.vod_metrics_widget)
        metrics_parent_layout.addWidget(self.icon_metrics_widget)
        self.downloading_metrics_widget.hide()
        bottom_row.addWidget(self.downloading_metrics_widget)

        # 3-3. 일반 상태(대기, 완료, 실패 등) 텍스트 라벨
        self.status_label = QLabel(self)
        self.status_label.setStyleSheet("color: #9ca3af; font-size: 11px;")
        bottom_row.addWidget(self.status_label)

        info_layout.addLayout(bottom_row)
        main_layout.addLayout(info_layout, stretch=1)

    @property
    def has_local_media_file(self) -> bool:
        """다운로드 완료 또는 중단 시 실제로 재생/삭제할 수 있는 로컬 파일이 존재하는지 여부를 반환합니다."""
        target = getattr(self, "final_file_path", None) or self.target_path
        if target is not None:
            try:
                p = Path(target)
                return p.is_file() and p.stat().st_size > 0
            except (OSError, ValueError):
                return False
        return False

    def _show_hover_toolbar(self, visible: bool) -> None:
        """2번 위치 우상단 호버 툴바 버튼들의 가시성을 상태에 따라 제어합니다."""
        if visible:
            stopped_without_file = getattr(self, "_stopped_without_file", False)
            should_hide_file_actions = stopped_without_file

            # 파일 삭제 [🗑️]: 파일이 없는 취소 카드가 아닌 경우에만 노출
            if not should_hide_file_actions and (
                self.status
                in (
                    TaskStatus.DOWNLOADING,
                    TaskStatus.STOPPED,
                    TaskStatus.COMPLETED,
                )
            ):
                self.action_delete_file_btn.show()
            else:
                self.action_delete_file_btn.hide()

            # 재시도(🔄) 버튼은 4번 위치에만 단일 배치하므로 2번 위치 호버 툴바에서는 항상 숨김
            self.retry_btn.hide()

            # 폴더 열기(📁)와 목록에서 제거(✕)는 호버 시 상시 노출
            self.open_folder_btn.show()
            self.delete_btn.show()

            # 재생(▶) 버튼: 완료 또는 중단 상태(파일 없는 취소 제외)에서 활성화
            if not should_hide_file_actions and (
                self.status in (TaskStatus.COMPLETED, TaskStatus.STOPPED)
            ):
                self.play_btn.show()
            else:
                self.play_btn.hide()
        else:
            self.open_folder_btn.hide()
            self.play_btn.hide()
            self.retry_btn.hide()
            self.action_delete_file_btn.hide()
            self.delete_btn.hide()

    def enterEvent(self, event: QEnterEvent | None) -> None:  # noqa: N802
        super().enterEvent(event)
        self._show_hover_toolbar(True)

    def leaveEvent(self, event: QEvent | None) -> None:  # noqa: N802
        super().leaveEvent(event)
        self._show_hover_toolbar(False)

    def contextMenuEvent(  # noqa: N802
        self, event: QContextMenuEvent | None
    ) -> None:
        """우클릭 컨텍스트 메뉴: 다시 시작, 완료, 오류 상세, URL 복사 액션 지원."""
        if event is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #1e1e1e; color: #f3f4f6; border: 1px solid #374151; padding: 4px; border-radius: 4px; }"
            "QMenu::item { padding: 6px 20px; border-radius: 2px; font-size: 12px; }"
            "QMenu::item:selected { background-color: #374151; color: white; }"
            "QMenu::item:disabled { color: #6b7280; }"
        )

        # 1. 다시 시작
        retry_action = QAction("다시 시작", menu)
        is_retryable = self.status in (
            TaskStatus.STOPPED,
            TaskStatus.FAILED_DOWNLOAD,
        )
        retry_action.setEnabled(is_retryable)
        retry_action.triggered.connect(self._on_retry_clicked)
        menu.addAction(retry_action)

        # 2. 완료
        complete_action = QAction("완료", menu)
        can_complete = (
            self.status
            in (
                TaskStatus.STOPPED,
                TaskStatus.FAILED_DOWNLOAD,
                TaskStatus.FAILED_LOGIN_REQUIRED,
            )
            and self.has_local_media_file
        )
        complete_action.setEnabled(can_complete)
        complete_action.triggered.connect(self._on_complete_clicked)
        menu.addAction(complete_action)

        menu.addSeparator()

        # 3. 오류 상세 보기
        error_action = QAction("오류 상세 보기", menu)
        is_error = self.status in (
            TaskStatus.FAILED_INVALID,
            TaskStatus.FAILED_LOGIN_REQUIRED,
            TaskStatus.FAILED_DOWNLOAD,
        )
        error_action.setEnabled(is_error)
        error_action.triggered.connect(self.open_task_info_window)
        menu.addAction(error_action)

        # 4. URL 복사
        copy_action = QAction("URL 복사", menu)
        copy_action.triggered.connect(self._copy_url_to_clipboard)
        menu.addAction(copy_action)

        menu.exec(event.globalPos())

    def copy_url_to_clipboard(self) -> None:
        """현재 작업의 치지직 URL을 시스템 클립보드에 복사합니다 (공개 메서드)."""
        clipboard = QApplication.clipboard()
        if clipboard is not None and self.raw_url:
            clipboard.setText(self.raw_url)

    def trigger_retry(self) -> None:
        """다시 시작(재시도) 시그널을 방출합니다 (공개 메서드)."""
        self.retry_requested.emit(self.task_id)

    def trigger_complete(self) -> None:
        """현재 파일로 완료 확정 시그널을 방출합니다 (공개 메서드)."""
        self.complete_requested.emit(self.task_id)

    def _copy_url_to_clipboard(self) -> None:
        self.copy_url_to_clipboard()

    def _on_retry_clicked(self) -> None:
        self.trigger_retry()

    def _on_complete_clicked(self) -> None:
        self.trigger_complete()

    def eventFilter(  # noqa: N802
        self, watched: QObject | None, event: QEvent | None
    ) -> bool:
        if event is not None and watched in (self.progress_bar, self.pct_label):
            if event.type() == QEvent.Type.Enter:
                tip = self.progress_bar.toolTip()
                if tip:
                    QToolTip.showText(QCursor.pos(), tip, self.progress_bar)
            elif event.type() == QEvent.Type.Leave:
                QToolTip.hideText()
        return super().eventFilter(watched, event)

    def _detach_thumb_loader(self) -> None:
        """실행 중인 썸네일 로더 스레드를 안전하게 분리하여 백그라운드 종료를 대기하도록 보존합니다."""
        if self._thumb_loader is not None:
            if self._thumb_loader.isRunning():
                try:
                    self._thumb_loader.loaded.disconnect()
                except Exception:
                    pass
                loader = self._thumb_loader
                loader.setParent(None)
                _DETACHED_LOADERS.add(loader)
                loader.finished.connect(
                    lambda ref=loader: _DETACHED_LOADERS.discard(ref)
                )
                loader.finished.connect(loader.deleteLater)
                loader.quit()
            self._thumb_loader = None

    def close_info_window(self) -> None:
        """이 카드가 소유한 TaskInfoWindow를 안전하게 닫고 정리합니다."""
        from PyQt6 import sip

        if hasattr(self, "_info_win") and self._info_win is not None:
            if not sip.isdeleted(self._info_win):
                self._info_win.close()
            self._info_win = None

    def deleteLater(self) -> None:  # noqa: N802
        self.is_deleted = True
        self.close_info_window()
        self.section_popup.hide()
        self.spinner.stop()
        if hasattr(self, "thumb_spinner") and not sip.isdeleted(self.thumb_spinner):
            self.thumb_spinner.stop()
        self._detach_thumb_loader()
        self._detach_probe_worker()
        super().deleteLater()

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self.is_deleted = True
        self.close_info_window()
        self.section_popup.hide()
        self.spinner.stop()
        if hasattr(self, "thumb_spinner") and not sip.isdeleted(self.thumb_spinner):
            self.thumb_spinner.stop()
        self._detach_thumb_loader()
        self._detach_probe_worker()
        super().closeEvent(event)

    def _detach_probe_worker(self) -> None:
        """실행 중인 미디어 프로빙 워커를 안전하게 분리하여 백그라운드 종료를 대기하도록 보존합니다."""
        worker = self._probe_worker
        self._probe_worker = None
        if worker is not None:
            if worker.isRunning():
                try:
                    worker.probed.disconnect()
                except (TypeError, RuntimeError):
                    pass
                try:
                    worker.failed.disconnect()
                except (TypeError, RuntimeError):
                    pass
                try:
                    worker.finished.disconnect(self._on_probe_finished)
                except (TypeError, RuntimeError):
                    pass
                worker.setParent(None)
                _DETACHED_PROBE_WORKERS.add(worker)
                worker.finished.connect(
                    lambda ref=worker: _DETACHED_PROBE_WORKERS.discard(ref)
                )
                worker.finished.connect(worker.deleteLater)

    def attach_probe_worker(self, worker: Any) -> None:
        """비동기 미디어 프로빙 워커를 카드에 등록합니다."""
        self._detach_probe_worker()
        self._probe_worker = worker

    def _load_thumbnail(self, url: str) -> None:
        """비동기로 썸네일 이미지를 다운로드하여 라벨에 표시합니다."""
        if not url or self.is_deleted:
            return
        self._detach_thumb_loader()
        self._thumb_loader = ThumbnailLoaderThread(url, parent=self)
        self._thumb_loader.loaded.connect(self._on_thumbnail_loaded)
        self._thumb_loader.start()

    def _on_thumbnail_loaded(self, img_bytes: bytes) -> None:
        """다운로드된 썸네일 바이트를 QPixmap으로 변환하여 표시합니다."""
        if self.is_deleted or sip.isdeleted(self):
            return
        if not hasattr(self, "thumb_label") or sip.isdeleted(self.thumb_label):
            return
        if hasattr(self, "thumb_spinner") and not sip.isdeleted(self.thumb_spinner):
            self.thumb_spinner.stop()
            self.thumb_spinner.hide()
        pixmap = QPixmap()
        if pixmap.loadFromData(img_bytes):
            scaled = pixmap.scaled(
                120,
                68,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.thumb_label.setPixmap(scaled)
            self.thumb_label.setText("")

    def _populate_qualities(self, force_default: bool = False) -> None:
        """vod_info.formats 기반으로 실제 제공 가능한 화질 목록을 구성하고 설정의 기본 화질을 우선 선택합니다."""
        self.quality_combo.blockSignals(True)
        current_sel = (
            ""
            if force_default
            else (self.selected_quality or self.quality_combo.currentText())
        )
        self.quality_combo.clear()

        if not self.vod_info or not self.vod_info.formats:
            self.quality_combo.addItem("최고 화질")
            self.selected_quality = "최고 화질"
            self.quality_combo.blockSignals(False)
            return

        seen: set[str] = set()
        qualities: list[str] = []
        valid_fmts = sorted(
            [f for f in self.vod_info.formats if f.height],
            key=lambda f: (f.height or 0, f.fps or 0),
            reverse=True,
        )
        for fmt in valid_fmts:
            fps_str = f"{int(fmt.fps)}" if fmt.fps and fmt.fps > 30 else ""
            label = f"{fmt.height}p{fps_str}"
            if label not in seen:
                seen.add(label)
                qualities.append(label)

        if not qualities:
            qualities.append("최고 화질")

        self.quality_combo.addItems(qualities)

        settings = get_current_settings()
        default_pref = settings.default_quality
        matched_quality = match_default_quality(qualities, default_pref)

        if current_sel and current_sel in qualities:
            self.quality_combo.setCurrentText(current_sel)
        else:
            self.quality_combo.setCurrentText(matched_quality)

        self.selected_quality = self.quality_combo.currentText()
        self.quality_combo.blockSignals(False)

    def _on_quality_selected(self, text: str) -> None:
        if text:
            self.selected_quality = text
            dur_str = format_duration(self.vod_info.duration) if self.vod_info else ""
            if self.status == TaskStatus.STOPPED:
                self.status_label.setText(f"{text} | 중지됨" if text else "중지됨")
            elif dur_str:
                self.status_label.setText(f"{text} | {dur_str}")

    def _on_change_folder_clicked(self) -> None:
        """📁 폴더 버튼 클릭 핸들러: 이 카드의 저장 폴더를 개별 변경합니다."""
        settings = get_current_settings()
        current_dir = str(self.custom_download_dir or settings.download_dir)
        selected = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", current_dir)
        if selected:
            self.custom_download_dir = Path(selected).resolve()
            self.folder_btn.setToolTip(f"저장 폴더: {self.custom_download_dir}")

    def _on_section_btn_clicked(self) -> None:
        """구간 설정 팝업을 버튼 아래에 표시하거나 숨깁니다."""
        if self.section_popup.isVisible():
            self.section_popup.hide()
        else:
            self.section_popup.show_below(self.section_btn)

    def _on_section_validity_changed(self, is_valid: bool) -> None:
        """구간 설정 유효성에 따라 다운로드 시작 버튼 활성화 상태 및 3번 위치 영상 길이를 연동합니다."""
        self.start_btn.setEnabled(is_valid)
        if self.status == TaskStatus.READY:
            self._update_display()

    def _get_effective_duration(self) -> int:
        """구간 설정이 적용되어 있으면 유효 구간 길이를, 아니면 원본 전체 길이를 반환합니다."""
        if not self.vod_info:
            return 0
        total_dur = float(self.vod_info.duration)
        if (
            self._applied_section_start is not None
            or self._applied_section_end is not None
        ):
            start_sec = (
                self._applied_section_start
                if self._applied_section_start is not None
                else 0.0
            )
            end_sec = (
                self._applied_section_end
                if self._applied_section_end is not None
                else total_dur
            )
            return max(0, int(round(end_sec - start_sec)))
        s_start, s_end = self.section_popup.get_section_range()
        if s_start is not None or s_end is not None:
            start_sec = s_start if s_start is not None else 0.0
            end_sec = s_end if s_end is not None else total_dur
            return max(0, int(round(end_sec - start_sec)))
        return int(round(total_dur))

    def _prompt_duplicate_resolution(self, filename: str) -> str:
        """동일 파일명 존재 시 처리 방법('overwrite', 'rename', 'cancel')을 묻는 대화상자를 띄웁니다."""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Chzzk Downloader")
        msg_box.setText(f"이미 동일한 이름의 파일이 존재합니다:\n{filename}")
        overwrite_btn = msg_box.addButton("덮어쓰기", QMessageBox.ButtonRole.AcceptRole)
        rename_btn = msg_box.addButton("이름 변경", QMessageBox.ButtonRole.ActionRole)
        msg_box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(rename_btn)
        msg_box.exec()

        clicked = msg_box.clickedButton()
        if clicked == overwrite_btn:
            return "overwrite"
        elif clicked == rename_btn:
            return "rename"
        return "cancel"

    def get_task_spec(self) -> TaskSpec:
        """이 카드의 다운로드 실행 명세(TaskSpec)를 불변 객체로 생성하여 반환합니다."""
        settings = get_current_settings()
        ext = (
            self.ext_combo.currentText()
            if hasattr(self, "ext_combo") and self.ext_combo.currentText()
            else settings.file_extension
        )
        quality = (
            self.selected_quality
            or (
                self.quality_combo.currentText()
                if hasattr(self, "quality_combo")
                else ""
            )
            or settings.default_quality
        )
        save_dir = self.custom_download_dir or settings.download_dir
        s_start, s_end = self.section_popup.get_section_range()
        if self.vod_info:
            filename = generate_vod_filename(
                self.vod_info, ext=ext, section_start=s_start, section_end=s_end
            )
            target = save_dir / filename
        else:
            target = save_dir

        expected_bytes = 0
        if self.vod_info:
            dur = (
                (s_end - s_start)
                if (s_start is not None and s_end is not None)
                else self.vod_info.duration
            )
            if dur and dur > 0:
                tbr: float | None = None
                for fmt in self.vod_info.formats:
                    if fmt.format_id == quality or fmt.resolution == quality:
                        if fmt.tbr and fmt.tbr > 0:
                            tbr = fmt.tbr
                            break
                if tbr is None:
                    if "1080" in quality:
                        tbr = 6000.0
                    elif "720" in quality:
                        tbr = 3000.0
                    elif "480" in quality:
                        tbr = 1500.0
                    else:
                        tbr = 5000.0
                expected_bytes = int(tbr * 1000 / 8 * dur)

        return TaskSpec(
            task_id=self.task_id,
            video_url=self.raw_url,
            is_live=self.is_live,
            title=self.vod_info.video_title if self.vod_info else "",
            streamer=self.vod_info.channel_name if self.vod_info else "",
            selected_quality=quality,
            selected_ext=ext,
            save_path=self.target_path or target,
            section_start=s_start,
            section_end=s_end,
            expected_total_bytes=expected_bytes,
        )

    def set_task_status(self, status: TaskStatus) -> None:
        """외부(TaskManager)로부터 상태 전이를 수신하여 카드를 갱신합니다."""
        if self.status == status:
            return
        self.status = status
        if status == TaskStatus.DOWNLOADING:
            self._has_started_download = True
            if self.section_popup.isVisible():
                self.section_popup.hide()
        self._update_display()
        self._apply_style()
        if self.underMouse():
            self._show_hover_toolbar(True)
        if status == TaskStatus.DOWNLOADING:
            self.download_started.emit()
        elif status == TaskStatus.STOPPED:
            self.download_stopped.emit()

    def set_completed(self, final_file_path: str | Path) -> None:
        """다운로드 완료 시 호출되어 최종 파일 경로를 보존하고 COMPLETED 상태로 전이합니다."""
        self._has_started_download = True
        if final_file_path and str(final_file_path).strip():
            self.final_file_path = Path(final_file_path)
        else:
            self.final_file_path = None
        if self._is_stopped:
            self._trigger_media_probe()
        if self.status != TaskStatus.COMPLETED:
            self.set_task_status(TaskStatus.COMPLETED)
        else:
            self._update_display()
            self._apply_style()
        if self.underMouse():
            self._show_hover_toolbar(True)

    def _trigger_media_probe(self) -> None:
        """R6 규칙을 준수하여 로컬 미디어 파일의 실제 duration과 size를 비동기 워커로 프로빙합니다."""
        target = self.final_file_path or self.target_path
        if not target:
            return
        p = Path(target)
        try:
            if not p.is_file() or p.stat().st_size < 1024:
                return
        except OSError:
            return

        from chzzk_downloader.core.ffmpeg_manager import (
            check_media_container_magic_bytes,
            is_ffmpeg_available,
        )

        if not is_ffmpeg_available(auto_download=False):
            return

        is_valid_media, _ = check_media_container_magic_bytes(p)
        if not is_valid_media:
            return

        from chzzk_downloader.gui.workers import MediaProbeWorker

        if self._probe_worker is not None and self._probe_worker.isRunning():
            return

        worker = MediaProbeWorker(self.task_id, p, parent=None)
        worker.probed.connect(self._on_media_probed)
        worker.finished.connect(self._on_probe_finished)
        worker.finished.connect(worker.deleteLater)
        self._probe_worker = worker
        worker.start()

    def _on_probe_finished(self) -> None:
        """미디어 프로빙 워커 종료 시 핸들러."""
        self._probe_worker = None

    def _on_media_probed(self, task_id: str, duration: float, size: int) -> None:
        """MediaProbeWorker의 프로빙 결과를 수신하여 3번 위치의 시간과 용량을 갱신합니다."""
        if duration > 0:
            dur_str = format_duration(int(round(duration)))
            self._stopped_duration_str = dur_str
            self.time_metric_label.setText(dur_str)
            if self.status == TaskStatus.STOPPED:
                self.status_label.setText(f"중지됨 ({dur_str})")
            elif self.status == TaskStatus.COMPLETED:
                file_size_str = self.size_metric_label.text()
                if file_size_str and file_size_str != "--":
                    self.status_label.setText(f"완료 ({dur_str} | {file_size_str})")
                else:
                    self.status_label.setText(f"완료 ({dur_str})")
        if size > 0:
            from chzzk_downloader.core.task_models import format_byte_size

            size_str = format_byte_size(size)
            self.size_metric_label.setText(size_str)

    def open_folder(self) -> None:
        """📁 폴더 열기: 탐색기를 열고 해당 파일을 선택(하이라이트)하거나 폴더를 엽니다."""
        # 1. COMPLETED 상태인 경우: 반드시 최종 파일이 존재해야 함 (없으면 경고 토스트)
        if self.status == TaskStatus.COMPLETED:
            target_file = getattr(self, "final_file_path", None)
            if (
                target_file
                and str(target_file).strip() not in ("", ".")
                and Path(target_file).is_file()
            ):
                import subprocess
                import sys

                if sys.platform == "win32":
                    try:
                        subprocess.Popen(f'explorer /select,"{target_file}"')
                        return
                    except Exception:
                        pass

                from PyQt6.QtCore import QUrl
                from PyQt6.QtGui import QDesktopServices

                QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(Path(target_file).parent))
                )
                return

            main_win = self.window()
            if hasattr(main_win, "toast") and hasattr(main_win.toast, "show_toast"):
                from chzzk_downloader.gui.toast import ToastType

                main_win.toast.show_toast(
                    f"파일을 찾을 수 없습니다: {self.final_file_path or ''}",
                    ToastType.WARNING,
                )
            return

        # 2. COMPLETED 상태가 아닌 경우 (예: READY 등): 대상 저장 폴더 열기
        settings = get_current_settings()
        target_dir = self.custom_download_dir or settings.download_dir
        if target_dir and Path(target_dir).exists():
            from PyQt6.QtCore import QUrl
            from PyQt6.QtGui import QDesktopServices

            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(target_dir).resolve()))
            )
            return

        main_win = self.window()
        if hasattr(main_win, "toast") and hasattr(main_win.toast, "show_toast"):
            from chzzk_downloader.gui.toast import ToastType

            main_win.toast.show_toast(
                f"폴더를 찾을 수 없습니다: {target_dir or ''}",
                ToastType.WARNING,
            )

    def play_media(self) -> None:
        """▶ 영상 재생: 시스템 기본 미디어 플레이어로 다운로드된 비디오를 실행합니다."""
        if (
            not self.final_file_path
            or str(self.final_file_path).strip() in ("", ".")
            or not self.final_file_path.is_file()
        ):
            main_win = self.window()
            if hasattr(main_win, "toast") and hasattr(main_win.toast, "show_toast"):
                from chzzk_downloader.gui.toast import ToastType

                main_win.toast.show_toast(
                    f"파일을 찾을 수 없습니다: {self.final_file_path or ''}",
                    ToastType.WARNING,
                )
            return

        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.final_file_path)))

    def set_waiting_position(self, position: int) -> None:
        """대기 순번을 갱신합니다 (음수/0은 대기 중... 기본 문구 유지)."""
        self.waiting_position = position if position > 0 else 0
        if self.status == TaskStatus.QUEUED:
            self.status_label.show()
            if self.waiting_position > 0:
                self.status_label.setText(
                    f"대기 중 (대기 순번: {self.waiting_position}번)"
                )
            else:
                self.status_label.setText("대기 중...")

    def update_progress(self, progress: TaskProgress) -> None:
        """다운로드/녹화 진행 상황을 실시간으로 갱신합니다."""
        if self.status != TaskStatus.DOWNLOADING:
            return
        self.last_progress = progress
        self.status_label.hide()
        if hasattr(self, "downloading_metrics_widget"):
            self.downloading_metrics_widget.show()

        if self.is_live:
            # C03-Live (라이브 녹화 중): 3번 위치 🕒 {녹화시간}   ⬇ {현재용량} (속도 제외)
            if hasattr(self, "vod_metrics_widget"):
                self.vod_metrics_widget.hide()
            if hasattr(self, "icon_metrics_widget"):
                self.icon_metrics_widget.show()
                self.time_metric_label.setText(progress.elapsed_str or "00:00")
                self.size_metric_label.setText(progress.downloaded_size_str or "0.0 B")
        else:
            # C03-VOD: 4번 위치(진행바+정수%) & 3번 위치([속도] | [남은 시간] | [⬇ 용량])
            if hasattr(self, "icon_metrics_widget"):
                self.icon_metrics_widget.hide()
            if hasattr(self, "vod_metrics_widget"):
                self.vod_metrics_widget.show()

            import math

            raw_pct = progress.percentage
            if raw_pct is None or math.isnan(raw_pct) or math.isinf(raw_pct):
                pct_int = 0
            else:
                pct_int = int(min(100, max(0, raw_pct)))
            self.progress_bar.setValue(pct_int)
            self.pct_label.setText(f"{pct_int}%")

            tip_text = progress.progress_summary
            if tip_text:
                if self.progress_bar.toolTip() != tip_text:
                    self.progress_bar.setToolTip(tip_text)
                if self.pct_label.toolTip() != tip_text:
                    self.pct_label.setToolTip(tip_text)
                if QToolTip.isVisible() and (
                    self.progress_bar.underMouse() or self.pct_label.underMouse()
                ):
                    QToolTip.showText(QCursor.pos(), tip_text, self.progress_bar)

            self.elapsed_label.setText(progress.elapsed_str or "00:00")

            if progress.speed_str:
                self.speed_label.setText(progress.speed_str)
            if progress.downloaded_bytes > 0:
                self.size_label.setText(f"⬇ {progress.downloaded_size_str}")

            # ETA(남은 시간) 가시성 제어:
            # 시작 직후 남은 시간이 없으면 ETA 숨김 -> 속도가 용량 바로 왼쪽에 배치
            # 남은 시간이 생기면 노출되어 속도 위치만 앞으로 이동
            if (
                progress.eta_seconds > 0
                and progress.eta_str
                and progress.eta_str != "00:00:00"
            ):
                self.eta_label.setText(progress.eta_str)
                self.eta_label.show()
                self.eta_sep_label.show()
            else:
                self.eta_label.hide()
                self.eta_sep_label.hide()

    def _on_delete_file_clicked(self) -> None:
        """2번 위치 [🗑️] 파일 삭제 클릭 핸들러 (M11 모달 확인 후 안전 삭제 및 카드 자동 제거)."""
        target = (
            getattr(self, "final_file_path", None)
            or self.target_path
            or getattr(self, "completed_file_path", None)
        )

        if not target and self.vod_info:
            settings = get_current_settings()
            save_dir = self.custom_download_dir or settings.download_dir
            ext = (
                self.ext_combo.currentText()
                if hasattr(self, "ext_combo") and self.ext_combo.currentText()
                else settings.file_extension
            )
            s_start, s_end = self.section_popup.get_section_range()
            filename = generate_vod_filename(
                self.vod_info, ext=ext, section_start=s_start, section_end=s_end
            )
            target = save_dir / filename

        filename_str = Path(target).name if target else "다운로드 파일"
        ok = ask_confirm_dialog(
            parent=self,
            text=f"다음 파일이 삭제됩니다:\n{filename_str}",
            title="Chzzk Downloader",
            is_danger=True,
        )
        if not ok:
            return

        # 다운로드 중인 경우 프로세스 먼저 안전 중지
        if self.status == TaskStatus.DOWNLOADING:
            self.request_stop_download.emit(self.task_id)

        # 실제 파일 안전 삭제 수행 (팟플레이어 등 재생 중 삭제 지원 및 .part 임시 파일 일괄 정리)
        success = False
        if target:
            success = _delete_file_safely(Path(target))
        else:
            success = True

        if not success:
            QMessageBox.warning(
                self,
                "Chzzk Downloader",
                f"파일을 삭제할 수 없습니다:\n{filename_str}\n\n다른 프로그램에서 사용 중이거나 쓰기 권한이 없습니다.",
            )
            return

        # T08 동영상 삭제 토스트 노출
        main_win = self.window()
        if main_win and hasattr(main_win, "show_file_deleted_toast"):
            main_win.show_file_deleted_toast(filename_str)
        elif main_win and hasattr(main_win, "toast"):
            safe_name = html.escape(filename_str)
            toast_html = (
                f'<span style="color: #ef4444; font-size: 14px;">🗑</span> '
                f'<span style="color: #ffffff;">{safe_name}</span>'
            )
            main_win.toast.show_toast(toast_html, auto_dismiss_ms=2500)

        # 작업 목록에서 카드를 자동으로 즉시 제거
        self.delete_requested.emit()

    def trigger_start_download(self) -> bool:
        """다운로드 시작 트리거: 파일 중복 검사 후 DOWNLOADING 또는 QUEUED 상태 진입을 요청합니다."""
        if self.section_popup.isVisible():
            self.section_popup.hide()
        if self.status != TaskStatus.READY:
            return False
        if not self.vod_info:
            return False

        from chzzk_downloader.core.ffmpeg_manager import is_ffmpeg_available

        if not is_ffmpeg_available(auto_download=False):
            self.download_blocked.emit(
                "FFmpeg를 사용할 수 없습니다. 환경설정에서 FFmpeg를 설정해주세요."
            )
            return False

        settings = get_current_settings()
        save_dir = self.custom_download_dir or settings.download_dir
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.download_blocked.emit(f"저장 폴더를 생성할 수 없습니다: {e}")
            return False

        s_start, s_end = self.section_popup.get_section_range()
        if s_start is not None or s_end is not None:
            from chzzk_downloader.core.section_parser import validate_section

            try:
                validate_section(s_start, s_end, duration=float(self.vod_info.duration))
            except ValueError as e:
                self.download_blocked.emit(f"⚠️ 올바른 구간을 입력해주세요: {e}")
                return False

        ext = self.ext_combo.currentText() or settings.file_extension
        filename = generate_vod_filename(
            self.vod_info, ext=ext, section_start=s_start, section_end=s_end
        )
        target_path = save_dir / filename

        # 동일한 파일명이 이미 존재할 경우 (옵션 A)
        if target_path.exists():
            choice = self._prompt_duplicate_resolution(filename)
            if choice == "overwrite":
                final_path = target_path
            elif choice == "rename":
                final_path = resolve_duplicate_filename(target_path)
            else:
                return False
        else:
            final_path = target_path

        self.section_popup.hide()

        self._stopped_duration_str = None
        self._is_stopped = False
        self._applied_section_start = s_start
        self._applied_section_end = s_end

        self.target_path = final_path
        if self.quality_combo.currentText():
            self.selected_quality = self.quality_combo.currentText()

        spec = self.get_task_spec()
        self.request_start_download.emit(spec)

        # MainWindow와 연결되어 있지 않은 독립 위젯(단위 테스트 등)인 경우에만 기본 전이
        if (
            self.receivers(self.request_start_download) == 0
            and self.status == TaskStatus.READY
        ):
            self.status = TaskStatus.DOWNLOADING
            self._update_display()
            self.download_started.emit()
        return True

    def _confirm_stop_dialog(self) -> bool:
        """다운로드 중지 확인 모달을 띄우고 승인 여부를 반환합니다 (확인/취소, 확인 하이라이트)."""
        return ask_confirm_dialog(
            parent=self,
            text="정말 중지하시겠습니까?",
        )

    def trigger_stop_download(self) -> bool:
        """다운로드 중지 트리거: 확인 모달 승인 시 안전 중단 및 완결(STOPPED) 상태로 전이."""
        if self.status != TaskStatus.DOWNLOADING:
            return False
        if not self._confirm_stop_dialog():
            return False

        if not self.has_local_media_file:
            self._stopped_without_file = True

        self.request_stop_download.emit(self.task_id)

        if self.status != TaskStatus.STOPPED:
            self.status = TaskStatus.STOPPED
            self._update_display()
            self._apply_style()
            self.download_stopped.emit()
        return True

    def reset_for_redownload(self) -> None:
        """동일 VOD 재입력 시 이전 세션 리소스 정리 및 클린 리셋 (충돌 방어 및 최신 설정 반영)."""
        self.error_message = ""
        self.error_type = ""
        self.traceback_str = ""
        self.final_file_path = None
        self._has_started_download = False
        self._stopped_without_file = False
        self._stopped_duration_str = None
        self._is_stopped = False
        self._applied_section_start = None
        self._applied_section_end = None
        self.selected_quality = ""
        self.custom_download_dir = None
        self.target_path = None
        self.waiting_position = 0
        self.quality_combo.blockSignals(True)
        self.quality_combo.clear()
        self.quality_combo.blockSignals(False)

        # 최신 환경설정의 기본 확장자 반영
        settings = get_current_settings()
        if settings.file_extension in AVAILABLE_EXTENSIONS:
            self.ext_combo.blockSignals(True)
            self.ext_combo.setCurrentText(settings.file_extension)
            self.ext_combo.blockSignals(False)

        self.section_popup.reset()

        self.status = TaskStatus.ANALYZING
        self._update_display()
        self._apply_style()

    def _update_display(self) -> None:
        """현재 상태에 따라 UI 텍스트 및 가시성을 갱신합니다."""
        if hasattr(self, "downloading_metrics_widget"):
            self.downloading_metrics_widget.hide()
            self.progress_bar.hide()

        if self.stopped_container is not None:
            self.stopped_container.hide()
        if self.failed_retry_btn is not None:
            self.failed_retry_btn.hide()
        if self.failed_complete_btn is not None:
            self.failed_complete_btn.hide()

        if hasattr(self, "thumb_spinner") and self.status != TaskStatus.ANALYZING:
            self.thumb_spinner.stop()
            self.thumb_spinner.hide()

        if self.status == TaskStatus.ANALYZING:
            # 유저 요구사항: 읽는 중… URL
            self.title_label.setText(f"읽는 중… {self.raw_url}")
            self.status_label.show()
            self.status_label.setText("분석 중...")
            self.auth_container.hide()
            self.ready_container.hide()
            self.vod_downloading_container.hide()
            self.live_recording_container.hide()
            self.completed_container.hide()
            self.spinner.stop()
            # 빈 화면에 분석 중 텍스트 대신 회색 회전 위젯으로 표시 (사용자 요구사항)
            self.thumb_label.setText("")
            if hasattr(self, "thumb_spinner"):
                self.thumb_spinner.show()
                self.thumb_spinner.start()

        elif self.status == TaskStatus.READY:
            self.status_label.show()
            if self.vod_info:
                self.title_label.setText(self.vod_info.display_name)
                dur = self._get_effective_duration()
                dur_str = format_duration(dur)
                quality_str = self.selected_quality or self.quality_combo.currentText()
                self.status_label.setText(
                    f"{quality_str} | {dur_str}" if quality_str else dur_str
                )
            self.auth_container.hide()
            self.ready_container.show()
            self.vod_downloading_container.hide()
            self.live_recording_container.hide()
            self.completed_container.hide()
            self.spinner.stop()
            if not (self.vod_info and self.vod_info.thumbnail_url):
                self.thumb_label.setText("VOD")

        elif self.status == TaskStatus.QUEUED:
            self.status_label.show()
            pos_text = (
                f" (대기 순번: {self.waiting_position}번)"
                if self.waiting_position > 0
                else ""
            )
            self.status_label.setText(f"대기 중{pos_text}")
            if self.vod_info:
                self.title_label.setText(self.vod_info.display_name)
            self.auth_container.hide()
            self.ready_container.hide()
            self.vod_downloading_container.hide()
            self.live_recording_container.hide()
            self.completed_container.hide()
            self.spinner.stop()
            if not (self.vod_info and self.vod_info.thumbnail_url):
                self.thumb_label.setText("대기")

        elif self.status == TaskStatus.COMPLETED:
            if hasattr(self, "downloading_metrics_widget"):
                self.downloading_metrics_widget.show()
            if hasattr(self, "vod_metrics_widget"):
                self.vod_metrics_widget.hide()
            self.status_label.hide()

            if self._is_stopped and self._stopped_duration_str:
                dur_str = self._stopped_duration_str
            else:
                dur = self._get_effective_duration()
                dur_str = format_duration(dur) if dur > 0 else ""
            file_size_str = ""
            target = (
                getattr(self, "final_file_path", None)
                or self.target_path
                or getattr(self, "completed_file_path", None)
            )

            if target:
                p = Path(target)
                if p.exists() and p.is_file():
                    from chzzk_downloader.core.task_models import format_byte_size

                    file_size_str = format_byte_size(p.stat().st_size)

            # C08: 우하단 🕒 {시간}   ⬇ {용량} 메트릭
            if hasattr(self, "icon_metrics_widget"):
                self.icon_metrics_widget.show()
                self.time_metric_label.setText(dur_str or "00:00")
                self.size_metric_label.setText(file_size_str or "--")

            # status_label 호환 텍스트 보존
            if dur_str and file_size_str:
                self.status_label.setText(f"완료 ({dur_str} | {file_size_str})")
            elif file_size_str:
                self.status_label.setText(f"완료 ({file_size_str})")
            elif dur_str:
                self.status_label.setText(f"완료 ({dur_str})")
            else:
                self.status_label.setText("완료")

            if self.vod_info:
                self.title_label.setText(self.vod_info.display_name)
            self.auth_container.hide()
            self.ready_container.hide()
            self.vod_downloading_container.hide()
            self.live_recording_container.hide()
            self.spinner.stop()

            # 4번 위치: VOD 완료 시 [Z] 단독, Live 완료 시 [Z] [📺▶]
            self.completed_container.show()
            self.completed_chzzk_badge.show()
            if self.is_live:
                self.completed_live_icon_label.show()
            else:
                self.completed_live_icon_label.hide()

            if not (self.vod_info and self.vod_info.thumbnail_url):
                self.thumb_label.setText("완료")

        elif self.status == TaskStatus.STOPPED:
            if self.vod_info:
                self.title_label.setText(self.vod_info.display_name)
            self.auth_container.hide()
            self.ready_container.hide()
            self.vod_downloading_container.hide()
            self.live_recording_container.hide()
            self.spinner.stop()

            # 일반 STOPPED (C08 완결 규격)
            if hasattr(self, "downloading_metrics_widget"):
                self.downloading_metrics_widget.show()
            if hasattr(self, "vod_metrics_widget"):
                self.vod_metrics_widget.hide()
            self.status_label.hide()

            if self.is_live:
                dur_str = (
                    self.last_progress.elapsed_str
                    if self.last_progress and self.last_progress.elapsed_str
                    else "00:00"
                )
            elif (
                self.last_progress
                and self.last_progress.percentage > 0
                and self.vod_info
                and self.vod_info.duration > 0
            ):
                effective_total = self._get_effective_duration()
                base_duration = (
                    effective_total if effective_total > 0 else self.vod_info.duration
                )
                actual_sec = int(
                    base_duration * (self.last_progress.percentage / 100.0)
                )
                dur_str = format_duration(actual_sec)
            elif self.last_progress and self.last_progress.elapsed_str:
                dur_str = self.last_progress.elapsed_str
            else:
                dur = self._get_effective_duration()
                dur_str = format_duration(dur) if dur > 0 else "00:00"

            self._stopped_duration_str = dur_str

            file_size_str = ""
            target = (
                getattr(self, "final_file_path", None)
                or self.target_path
                or getattr(self, "completed_file_path", None)
            )
            if target:
                p = Path(target)
                if p.exists() and p.is_file():
                    from chzzk_downloader.core.task_models import format_byte_size

                    file_size_str = format_byte_size(p.stat().st_size)

            if hasattr(self, "icon_metrics_widget"):
                self.icon_metrics_widget.show()
                self.time_metric_label.setText(dur_str or "00:00")
                self.size_metric_label.setText(file_size_str or "--")

            self.status_label.setText(f"중지됨 ({dur_str})" if dur_str else "중지됨")
            self.completed_container.hide()
            self.stopped_container.show()
            if self.has_local_media_file:
                self.stopped_complete_btn.show()
            else:
                self.stopped_complete_btn.hide()
            if self.last_progress:
                pct_val = int(round(self.last_progress.percentage))
                self.stopped_progress_bar.setValue(pct_val)
                self.stopped_pct_label.setText(f"{pct_val}%")
            else:
                self.stopped_progress_bar.setValue(0)
                self.stopped_pct_label.setText("0%")
            if not (self.vod_info and self.vod_info.thumbnail_url):
                self.thumb_label.setText("중지")

            self._is_stopped = True
            self._trigger_media_probe()

        elif self.status == TaskStatus.DOWNLOADING:
            self.status_label.hide()
            if hasattr(self, "downloading_metrics_widget"):
                self.downloading_metrics_widget.show()

            if self.vod_info:
                self.title_label.setText(self.vod_info.display_name)
            self.auth_container.hide()
            self.ready_container.hide()
            self.completed_container.hide()

            if self.is_live:
                self.vod_downloading_container.hide()
                self.live_recording_container.show()
                if hasattr(self, "vod_metrics_widget"):
                    self.vod_metrics_widget.hide()
                if hasattr(self, "icon_metrics_widget"):
                    self.icon_metrics_widget.show()
                self.spinner.start()
            else:
                self.spinner.stop()
                self.live_recording_container.hide()
                self.vod_downloading_container.show()
                self.progress_bar.show()
                if self.is_section_download:
                    self.stop_btn.hide()
                else:
                    self.stop_btn.show()
                if hasattr(self, "icon_metrics_widget"):
                    self.icon_metrics_widget.hide()
                if hasattr(self, "vod_metrics_widget"):
                    self.vod_metrics_widget.show()

        elif self.status == TaskStatus.FAILED_LOGIN_REQUIRED:
            self.title_label.setText(f"Login required; Please login\n{self.raw_url}")
            # C06: 3번 위치 상태 표시는 불필요하므로 숨김
            self.status_label.setText("")
            self.status_label.hide()
            self.auth_container.show()
            self.chzzk_badge.show()
            self.error_info_btn.show()
            self.error_info_btn.setToolTip("작업 정보")
            self.cookie_btn.show()
            self.login_btn.show()
            self.failed_retry_btn.hide()
            if self.has_local_media_file:
                self.failed_complete_btn.show()
            else:
                self.failed_complete_btn.hide()
            self.ready_container.hide()
            self.vod_downloading_container.hide()
            self.live_recording_container.hide()
            self.completed_container.hide()
            self.spinner.stop()
            self.thumb_label.setText("인증 필요")

        elif self.status == TaskStatus.FAILED_INVALID:
            self.title_label.setText(f"Invalid: {self.raw_url}")
            # C05: 3번 위치 상태 표시는 불필요하므로 숨김
            self.status_label.setText("")
            self.status_label.hide()
            self.auth_container.show()
            self.chzzk_badge.show()
            self.error_info_btn.show()
            self.error_info_btn.setToolTip("작업 정보")
            self.cookie_btn.hide()
            self.login_btn.hide()
            self.failed_retry_btn.hide()
            self.failed_complete_btn.hide()
            self.ready_container.hide()
            self.vod_downloading_container.hide()
            self.live_recording_container.hide()
            self.completed_container.hide()
            self.spinner.stop()
            self.thumb_label.setText("✕")

        elif self.status == TaskStatus.FAILED_DOWNLOAD:
            self.title_label.setText(f"Download failed: {self.raw_url}")
            # C07: 3번 위치 상태 표시는 불필요하므로 숨김
            self.status_label.setText("")
            self.status_label.hide()
            self.auth_container.show()
            self.chzzk_badge.show()
            self.error_info_btn.show()
            self.error_info_btn.setToolTip("작업 정보")
            self.cookie_btn.hide()
            self.login_btn.hide()
            self.failed_retry_btn.show()
            if self.has_local_media_file:
                self.failed_complete_btn.show()
            else:
                self.failed_complete_btn.hide()
            self.ready_container.hide()
            self.vod_downloading_container.hide()
            self.live_recording_container.hide()
            self.completed_container.hide()
            self.spinner.stop()
            self.thumb_label.setText("실패")

    def _apply_style(self) -> None:
        """상태에 따라 카드의 테두리 및 배경 하이라이트를 적용합니다."""
        if self.status in (
            TaskStatus.FAILED_INVALID,
            TaskStatus.FAILED_LOGIN_REQUIRED,
        ):
            # 빨간색 좌측 5px 바 + 은은한 레드 틴트 배경
            self.setStyleSheet(
                "#TaskCardWidget {"
                "  background-color: rgba(239, 68, 68, 0.10);"
                "  border: 1px solid rgba(239, 68, 68, 0.35);"
                "  border-left: 5px solid #ef4444;"
                "  border-radius: 6px;"
                "}"
            )
            self.title_label.setStyleSheet(
                "color: #ef4444; font-size: 13px; font-weight: 600;"
            )
            self.status_label.setStyleSheet(
                "color: #ef4444; font-size: 11px; font-weight: 500;"
            )
            self.thumb_label.setStyleSheet(
                "background-color: rgba(239, 68, 68, 0.2); color: #ef4444; border-radius: 4px; font-weight: bold; font-size: 12px;"
            )
        elif self.status == TaskStatus.FAILED_DOWNLOAD:
            # 주황색 좌측 5px 바 + 은은한 주황색 틴트 배경 (T0110 대응)
            self.setStyleSheet(
                "#TaskCardWidget {"
                "  background-color: rgba(245, 158, 11, 0.10);"
                "  border: 1px solid rgba(245, 158, 11, 0.35);"
                "  border-left: 5px solid #f59e0b;"
                "  border-radius: 6px;"
                "}"
            )
            self.title_label.setStyleSheet(
                "color: #f59e0b; font-size: 13px; font-weight: 600;"
            )
            self.status_label.setStyleSheet(
                "color: #f59e0b; font-size: 11px; font-weight: 500;"
            )
            self.thumb_label.setStyleSheet(
                "background-color: rgba(245, 158, 11, 0.2); color: #f59e0b; border-radius: 4px; font-weight: bold; font-size: 12px;"
            )
        elif self.status == TaskStatus.STOPPED:
            # 슬레이트 블루/그레이 좌측 5px 바 + 은은한 틴트 배경 (중지됨 상태 식별)
            self.setStyleSheet(
                "#TaskCardWidget {"
                "  background-color: rgba(100, 116, 139, 0.08);"
                "  border: 1px solid rgba(100, 116, 139, 0.35);"
                "  border-left: 5px solid #64748b;"
                "  border-radius: 6px;"
                "}"
                "#TaskCardWidget:hover {"
                "  border: 1px solid #64748b;"
                "  background-color: rgba(100, 116, 139, 0.12);"
                "}"
            )
            self.title_label.setStyleSheet(
                "color: #94a3b8; font-size: 13px; font-weight: 600;"
            )
            self.status_label.setStyleSheet(
                "color: #94a3b8; font-size: 11px; font-weight: 500;"
            )
            self.thumb_label.setStyleSheet(
                "background-color: rgba(100, 116, 139, 0.2); color: #94a3b8; border-radius: 4px; font-weight: bold; font-size: 12px;"
            )
        else:
            # 기본 정상 카드 스타일 (읽는 중, 다운로드 중 등 현행 유지)
            self.setStyleSheet(
                "#TaskCardWidget {"
                "  background-color: #1e1e1e;"
                "  border: 1px solid #333333;"
                "  border-radius: 6px;"
                "}"
                "#TaskCardWidget:hover {"
                "  border: 1px solid #4b5563;"
                "  background-color: #252525;"
                "}"
            )
            self.title_label.setStyleSheet(
                "color: #f3f4f6; font-size: 13px; font-weight: 600;"
            )
            self.status_label.setStyleSheet("color: #9ca3af; font-size: 11px;")
            self.thumb_label.setStyleSheet(
                "background-color: #2a2a2a; color: #888888; border-radius: 4px; font-weight: bold; font-size: 12px;"
            )

    def update_with_vod_info(self, info: VodInfo) -> None:
        """yt-dlp VOD 분석 완료 시 메타데이터를 반영하여 준비 완료 상태로 갱신합니다."""
        self.status = TaskStatus.READY
        self.vod_info = info
        self.video_no = info.video_no or self.video_no
        if info.video_no:
            self.task_id = info.video_no
        self._populate_qualities(force_default=True)
        # 설정의 기본 확장자 반영
        settings = get_current_settings()
        if settings.file_extension in AVAILABLE_EXTENSIONS:
            self.ext_combo.blockSignals(True)
            self.ext_combo.setCurrentText(settings.file_extension)
            self.ext_combo.blockSignals(False)

        if info.can_section_download:
            self.section_btn.show()
            self.section_popup.set_duration(float(info.duration))
        else:
            self.section_btn.hide()

        self._update_display()
        self._apply_style()
        if info.thumbnail_url:
            self._load_thumbnail(info.thumbnail_url)

    def set_failed(
        self,
        status: TaskStatus,
        error_message: str = "",
        error_type: str = "",
        traceback_str: str = "",
    ) -> None:
        """분석 실패 또는 오류 상태로 카드를 갱신하고 에러 상세를 보존합니다."""
        self.status = status
        self.error_message = error_message
        self.error_type = error_type
        self.traceback_str = traceback_str
        self._update_display()
        self._apply_style()

    def _on_chzzk_badge_clicked(self) -> None:
        """치지직 뱃지 클릭 핸들러: 확인/취소 모달 후 기본 브라우저로 해당 URL 이동."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        ok = ask_confirm_dialog(
            parent=self,
            text=f"해당 링크로 이동합니다.\n\n이동하시겠습니까?\n{self.raw_url}",
            title="Chzzk Downloader",
        )
        if ok:
            QDesktopServices.openUrl(QUrl(self.raw_url))

    def open_task_info_window(self) -> None:
        """작업 정보 비모달 윈도우를 엽니다 (최소화/최대화 가능, 메인 창 조작 영향 없음)."""
        from PyQt6 import sip

        from chzzk_downloader.gui.task_info_window import TaskInfoWindow

        if (
            not hasattr(self, "_info_win")
            or self._info_win is None
            or sip.isdeleted(self._info_win)
        ):
            self._info_win = TaskInfoWindow(self)
            self._info_win.show()
        else:
            self._info_win.refresh_info()
            self._info_win.show()
            self._info_win.activateWindow()
            self._info_win.raise_()
