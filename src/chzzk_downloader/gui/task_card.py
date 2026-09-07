"""다운로드 작업 카드(Task Card) 위젯 모듈."""

import urllib.request
from enum import Enum
from pathlib import Path
from typing import Any

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QEnterEvent, QPainter, QPaintEvent, QPen, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chzzk_downloader.config import AVAILABLE_EXTENSIONS, DEFAULT_USER_AGENT
from chzzk_downloader.core.filename_generator import (
    generate_vod_filename,
    resolve_duplicate_filename,
)
from chzzk_downloader.core.settings_manager import get_current_settings
from chzzk_downloader.core.url_parser import parse_chzzk_vod_url
from chzzk_downloader.core.ytdlp import VodInfo
from chzzk_downloader.gui.dialogs import ask_confirm_dialog


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


class TaskStatus(Enum):
    """작업 카드 상태 열거형."""

    ANALYZING = "ANALYZING"
    READY = "READY"
    DOWNLOADING = "DOWNLOADING"
    STOPPED = "STOPPED"
    FAILED_INVALID = "FAILED_INVALID"
    FAILED_LOGIN_REQUIRED = "FAILED_LOGIN_REQUIRED"


class SpinnerWidget(QWidget):
    """버퍼링 회전 인디케이터 위젯."""

    def __init__(self, size: int = 14, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)

    def _rotate(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start(50)

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
        self._angle = 0
        self.update()

    def paintEvent(self, event: QPaintEvent | None) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#3b82f6"), 2)
        painter.setPen(pen)
        painter.translate(self._size / 2, self._size / 2)
        painter.rotate(self._angle)
        span = 270 * 16
        r = (self._size - 3) / 2
        painter.drawArc(int(-r), int(-r), int(2 * r), int(2 * r), 0, span)


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

    def __init__(
        self,
        raw_url: str,
        status: TaskStatus = TaskStatus.ANALYZING,
        vod_info: VodInfo | None = None,
        video_no: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.raw_url = raw_url
        self.status = status
        self.vod_info = vod_info
        self.video_no = (
            video_no
            or (vod_info.video_no if vod_info else "")
            or (parse_chzzk_vod_url(raw_url) or "")
        )
        self.error_message: str = ""
        self.is_deleted: bool = False
        self._thumb_loader: ThumbnailLoaderThread | None = None

        self.custom_download_dir: Path | None = None
        self.target_path: Path | None = None
        self.selected_quality: str = ""

        self._init_ui()
        if self.vod_info:
            self._populate_qualities()
        self._update_display()
        self._apply_style()

        if self.vod_info and self.vod_info.thumbnail_url:
            self._load_thumbnail(self.vod_info.thumbnail_url)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(400, 88)

    def _init_ui(self) -> None:
        self.setObjectName("TaskCardWidget")
        self.setMinimumHeight(88)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(12)

        # 좌측: 썸네일 박스 (120x68px, 16:9)
        self.thumb_label = QLabel(self)
        self.thumb_label.setFixedSize(120, 68)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setScaledContents(True)
        self.thumb_label.setStyleSheet(
            "background-color: #2a2a2a; color: #888888; border-radius: 4px; font-weight: bold; font-size: 12px;"
        )
        self.thumb_label.setText("VOD")
        main_layout.addWidget(self.thumb_label)

        # 우측: 4분면 정보 영역
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 2, 0, 2)
        info_layout.setSpacing(4)

        # 상단 행: 1번 위치(좌상단 타이틀) + 2번 위치(우상단 액션 아이콘)
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)

        # 1번 위치 (좌상단): 작업명 / 상태 표시 라벨 (좌측 정렬 줄바꿈 지원)
        self.title_label = QLabel(self)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.title_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        top_row.addWidget(self.title_label, stretch=1)

        # 2번 위치 (우상단): 회색조 액션 아이콘 그룹 (삭제 ✕ 버튼)
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

        # 4-1. 인증 필요 컨테이너
        self.auth_container = QWidget(self.action_container)
        auth_layout = QHBoxLayout(self.auth_container)
        auth_layout.setContentsMargins(0, 0, 0, 0)
        auth_layout.setSpacing(6)

        self.cookie_btn = QPushButton("쿠키 설정", self.auth_container)
        self.cookie_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cookie_btn.setStyleSheet(
            "QPushButton { background-color: #3b82f6; color: white; border: none; border-radius: 3px; padding: 2px 8px; font-size: 11px; }"
            "QPushButton:hover { background-color: #2563eb; }"
        )
        self.login_btn = QPushButton("네이버 로그인", self.auth_container)
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.setStyleSheet(
            "QPushButton { background-color: #03c75a; color: white; border: none; border-radius: 3px; padding: 2px 8px; font-size: 11px; }"
            "QPushButton:hover { background-color: #02b150; }"
        )
        self.cookie_btn.clicked.connect(self.request_open_cookies.emit)
        self.login_btn.clicked.connect(self.request_naver_login.emit)
        auth_layout.addWidget(self.cookie_btn)
        auth_layout.addWidget(self.login_btn)
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

        ready_layout.addWidget(self.quality_combo)
        ready_layout.addWidget(self.ext_combo)
        ready_layout.addWidget(self.folder_btn)
        ready_layout.addWidget(self.start_btn)
        self.ready_container.hide()

        # 4-3. 다운로드 실행 중 컨테이너 (녹화 중… + 버퍼링 회전 + ■ 중지 버튼)
        self.downloading_container = QWidget(self.action_container)
        downloading_layout = QHBoxLayout(self.downloading_container)
        downloading_layout.setContentsMargins(0, 0, 0, 0)
        downloading_layout.setSpacing(6)

        self.recording_label = QLabel("녹화 중…", self.downloading_container)
        self.recording_label.setStyleSheet(
            "color: #ef4444; font-size: 11px; font-weight: 600;"
        )

        self.spinner = SpinnerWidget(size=14, parent=self.downloading_container)

        self.stop_btn = QPushButton("■", self.downloading_container)
        self.stop_btn.setToolTip("다운로드 중지")
        self.stop_btn.setFixedSize(22, 22)
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #ef4444; border: none; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background-color: #374151; color: #f87171; border-radius: 4px; }"
        )
        self.stop_btn.clicked.connect(self.trigger_stop_download)

        downloading_layout.addWidget(self.recording_label)
        downloading_layout.addWidget(self.spinner)
        downloading_layout.addWidget(self.stop_btn)
        self.downloading_container.hide()

        action_layout.addWidget(self.auth_container)
        action_layout.addWidget(self.ready_container)
        action_layout.addWidget(self.downloading_container)

        bottom_row.addWidget(self.action_container)
        bottom_row.addStretch()

        # 3번 위치 (우하단): 재생 시간, 화질, 진행/실패 상태 라벨
        self.status_label = QLabel(self)
        self.status_label.setStyleSheet("color: #9ca3af; font-size: 11px;")
        bottom_row.addWidget(self.status_label)

        info_layout.addLayout(bottom_row)
        main_layout.addLayout(info_layout, stretch=1)

    def enterEvent(self, event: QEnterEvent | None) -> None:  # noqa: N802
        super().enterEvent(event)
        self.delete_btn.show()

    def leaveEvent(self, event: QEvent | None) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.delete_btn.hide()

    def deleteLater(self) -> None:  # noqa: N802
        self.is_deleted = True
        self.spinner.stop()
        if self._thumb_loader is not None and self._thumb_loader.isRunning():
            try:
                self._thumb_loader.loaded.disconnect()
            except Exception:
                pass
            self._thumb_loader.quit()
            self._thumb_loader.wait()
        super().deleteLater()

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self.is_deleted = True
        self.spinner.stop()
        if self._thumb_loader is not None and self._thumb_loader.isRunning():
            try:
                self._thumb_loader.loaded.disconnect()
            except Exception:
                pass
            self._thumb_loader.quit()
            self._thumb_loader.wait()
        super().closeEvent(event)

    def _load_thumbnail(self, url: str) -> None:
        """비동기로 썸네일 이미지를 다운로드하여 라벨에 표시합니다."""
        if not url or self.is_deleted:
            return
        if self._thumb_loader is not None and self._thumb_loader.isRunning():
            try:
                self._thumb_loader.loaded.disconnect()
            except Exception:
                pass
            self._thumb_loader.quit()
            self._thumb_loader.wait()
        self._thumb_loader = ThumbnailLoaderThread(url, parent=self)
        self._thumb_loader.loaded.connect(self._on_thumbnail_loaded)
        self._thumb_loader.start()

    def _on_thumbnail_loaded(self, img_bytes: bytes) -> None:
        """다운로드된 썸네일 바이트를 QPixmap으로 변환하여 표시합니다."""
        if self.is_deleted or sip.isdeleted(self):
            return
        if not hasattr(self, "thumb_label") or sip.isdeleted(self.thumb_label):
            return
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

    def _prompt_duplicate_resolution(self, filename: str) -> str:
        """동일 파일명 존재 시 처리 방법('overwrite', 'rename', 'cancel')을 묻는 대화상자를 띄웁니다."""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Chzzk Downloader")
        msg_box.setText(
            f"이미 동일한 이름의 파일이 존재합니다:\n{filename}\n\n어떻게 처리하시겠습니까?"
        )
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

    def trigger_start_download(self) -> bool:
        """다운로드 시작 트리거: 파일 중복 검사 후 DOWNLOADING 상태로 진입합니다."""
        if not self.vod_info:
            return False

        settings = get_current_settings()
        save_dir = self.custom_download_dir or settings.download_dir
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        ext = (
            self.ext_combo.currentText()
            if hasattr(self, "ext_combo") and self.ext_combo.currentText()
            else settings.file_extension
        )
        filename = generate_vod_filename(self.vod_info, ext=ext)
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

        self.target_path = final_path
        if self.quality_combo.currentText():
            self.selected_quality = self.quality_combo.currentText()

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
        if not self._confirm_stop_dialog():
            return False

        # 중지된 후에는 완결된 작업으로 처리되어 4번 위치에 대기 컨트롤이 나타나지 않음
        self.status = TaskStatus.STOPPED
        self._update_display()
        self.download_stopped.emit()
        return True

    def reset_for_redownload(self) -> None:
        """동일 VOD 재입력 시 이전 세션 리소스 정리 및 클린 리셋 (충돌 방어 및 최신 설정 반영)."""
        if self.status in (TaskStatus.DOWNLOADING, TaskStatus.STOPPED):
            self.status = TaskStatus.READY
        self.error_message = ""
        self.selected_quality = ""
        self.custom_download_dir = None
        self.target_path = None
        self.quality_combo.blockSignals(True)
        self.quality_combo.clear()
        self.quality_combo.blockSignals(False)

        # 최신 환경설정의 기본 확장자 반영
        settings = get_current_settings()
        if settings.file_extension in AVAILABLE_EXTENSIONS:
            self.ext_combo.blockSignals(True)
            self.ext_combo.setCurrentText(settings.file_extension)
            self.ext_combo.blockSignals(False)

        self.status = TaskStatus.ANALYZING
        self._update_display()
        self._apply_style()

    def _update_display(self) -> None:
        """현재 상태에 따라 UI 텍스트 및 가시성을 갱신합니다."""
        if self.status == TaskStatus.ANALYZING:
            # 유저 요구사항: 읽는 중… URL
            self.title_label.setText(f"읽는 중… {self.raw_url}")
            self.status_label.setText("분석 중...")
            self.auth_container.hide()
            self.ready_container.hide()
            self.downloading_container.hide()
            self.spinner.stop()
            self.thumb_label.setText("분석 중")

        elif self.status == TaskStatus.READY:
            if self.vod_info:
                self.title_label.setText(self.vod_info.display_name)
                dur_str = format_duration(self.vod_info.duration)
                quality_str = self.selected_quality or self.quality_combo.currentText()
                self.status_label.setText(
                    f"{quality_str} | {dur_str}" if quality_str else dur_str
                )
            self.auth_container.hide()
            self.ready_container.show()
            self.downloading_container.hide()
            self.spinner.stop()
            if not (self.vod_info and self.vod_info.thumbnail_url):
                self.thumb_label.setText("VOD")

        elif self.status == TaskStatus.DOWNLOADING:
            if self.vod_info:
                self.title_label.setText(self.vod_info.display_name)
                dur_str = format_duration(self.vod_info.duration)
                quality_str = self.selected_quality or self.quality_combo.currentText()
                self.status_label.setText(
                    f"{quality_str} | {dur_str}" if quality_str else dur_str
                )
            self.auth_container.hide()
            self.ready_container.hide()
            self.downloading_container.show()
            self.spinner.start()

        elif self.status == TaskStatus.STOPPED:
            if self.vod_info:
                self.title_label.setText(self.vod_info.display_name)
                dur_str = format_duration(self.vod_info.duration)
                quality_str = self.selected_quality or self.quality_combo.currentText()
                self.status_label.setText(
                    f"{quality_str} | 중지됨" if quality_str else "중지됨"
                )
            else:
                self.status_label.setText("중지됨")
            # 4번 위치 컨트롤 모두 숨김 (재개 불가 완결 작업)
            self.auth_container.hide()
            self.ready_container.hide()
            self.downloading_container.hide()
            self.spinner.stop()
            if not (self.vod_info and self.vod_info.thumbnail_url):
                self.thumb_label.setText("VOD")

        elif self.status == TaskStatus.FAILED_LOGIN_REQUIRED:
            self.title_label.setText(f"Login required; Please login: {self.raw_url}")
            self.status_label.setText("로그인 필요")
            self.auth_container.show()
            self.ready_container.hide()
            self.downloading_container.hide()
            self.spinner.stop()
            self.thumb_label.setText("인증 필요")

        elif self.status == TaskStatus.FAILED_INVALID:
            self.title_label.setText(f"Invalid: {self.raw_url}")
            self.status_label.setText(self.error_message or "분석 실패")
            self.auth_container.hide()
            self.ready_container.hide()
            self.downloading_container.hide()
            self.spinner.stop()
            self.thumb_label.setText("✕")

    def _apply_style(self) -> None:
        """상태에 따라 카드의 테두리 및 배경 하이라이트를 적용합니다."""
        if self.status in (
            TaskStatus.FAILED_INVALID,
            TaskStatus.FAILED_LOGIN_REQUIRED,
        ):
            # 빨간색 시각적 하이라이트 스타일
            self.setStyleSheet(
                "#TaskCardWidget {"
                "  background-color: rgba(239, 68, 68, 0.12);"
                "  border: 1px solid #ef4444;"
                "  border-radius: 6px;"
                "}"
            )
            self.title_label.setStyleSheet(
                "color: #ef4444; font-size: 13px; font-weight: 600;"
            )
            self.thumb_label.setStyleSheet(
                "background-color: rgba(239, 68, 68, 0.2); color: #ef4444; border-radius: 4px; font-weight: bold; font-size: 12px;"
            )
        else:
            # 기본 정상 카드 스타일
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
            self.thumb_label.setStyleSheet(
                "background-color: #2a2a2a; color: #888888; border-radius: 4px; font-weight: bold; font-size: 12px;"
            )

    def update_with_vod_info(self, info: VodInfo) -> None:
        """yt-dlp VOD 분석 완료 시 메타데이터를 반영하여 준비 완료 상태로 갱신합니다."""
        self.status = TaskStatus.READY
        self.vod_info = info
        self.video_no = info.video_no or self.video_no
        self._populate_qualities(force_default=True)
        # 설정의 기본 확장자 반영
        settings = get_current_settings()
        if settings.file_extension in AVAILABLE_EXTENSIONS:
            self.ext_combo.blockSignals(True)
            self.ext_combo.setCurrentText(settings.file_extension)
            self.ext_combo.blockSignals(False)
        self._update_display()
        self._apply_style()
        if info.thumbnail_url:
            self._load_thumbnail(info.thumbnail_url)

    def set_failed(self, status: TaskStatus, error_message: str = "") -> None:
        """분석 실패 또는 오류 상태로 카드를 갱신하고 빨간색 하이라이트를 적용합니다."""
        self.status = status
        self.error_message = error_message
        self._update_display()
        self._apply_style()
