"""환경설정 Modeless 창 모듈 (T0106)."""

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chzzk_downloader.config import AVAILABLE_EXTENSIONS, AVAILABLE_QUALITIES
from chzzk_downloader.core.cookie_manager import (
    clear_cookies,
    export_cookie_file,
    get_cookie_status_summary,
    load_cookie_file,
)
from chzzk_downloader.core.settings_manager import (
    get_current_settings,
    update_current_settings,
)
from chzzk_downloader.gui.cookie_viewer_dialog import CookieViewerDialog
from chzzk_downloader.gui.dialogs import ask_confirm_dialog


class SettingsWindow(QDialog):
    """메인 창과 독립적으로 조작 가능한 Modeless 환경설정 창."""

    cookies_updated = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("환경설정")
        self.resize(520, 460)
        self.setModal(False)  # Modeless 창으로 메인 창 상호작용 허용

        self._init_ui()
        self.refresh_status()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # 1. 일반 설정 그룹 (T0108: 쿠키 관리보다 위쪽에 배치)
        self.general_group = QGroupBox("일반", self)
        general_layout = QVBoxLayout(self.general_group)
        general_layout.setContentsMargins(12, 14, 12, 14)
        general_layout.setSpacing(10)

        # 저장 폴더 라벨
        folder_label = QLabel("저장 폴더", self.general_group)
        folder_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        general_layout.addWidget(folder_label)

        # 저장 폴더 경로 및 폴더 아이콘 버튼
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self.folder_input = QLineEdit(self.general_group)
        self.folder_input.setReadOnly(True)  # 직접 입력 없이 탐색기로만 경로 지정
        self.folder_input.setPlaceholderText("기본 저장 폴더 경로")
        folder_row.addWidget(self.folder_input)

        self.folder_btn = QPushButton("📁", self.general_group)
        self.folder_btn.setToolTip("저장 폴더 선택")
        self.folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_btn.setFixedWidth(36)
        self.folder_btn.clicked.connect(self._on_choose_folder)
        folder_row.addWidget(self.folder_btn)
        general_layout.addLayout(folder_row)

        # 화질 및 확장자 드롭다운 행
        opts_row = QHBoxLayout()
        opts_row.setSpacing(12)

        quality_label = QLabel("기본 화질:", self.general_group)
        opts_row.addWidget(quality_label)
        self.quality_combo = QComboBox(self.general_group)
        self.quality_combo.addItems(list(AVAILABLE_QUALITIES))
        self.quality_combo.currentTextChanged.connect(self._on_quality_changed)
        opts_row.addWidget(self.quality_combo)

        opts_row.addSpacing(16)

        ext_label = QLabel("파일 확장자:", self.general_group)
        opts_row.addWidget(ext_label)
        self.ext_combo = QComboBox(self.general_group)
        self.ext_combo.addItems(list(AVAILABLE_EXTENSIONS))
        self.ext_combo.currentTextChanged.connect(self._on_ext_changed)
        opts_row.addWidget(self.ext_combo)

        opts_row.addStretch()
        general_layout.addLayout(opts_row)

        # VOD 자동 다운로드 토글 스위치 행 (T0109)
        from chzzk_downloader.gui.switch_widget import SwitchWidget

        auto_row = QHBoxLayout()
        auto_row.setSpacing(12)
        auto_label = QLabel("VOD 자동 다운로드:", self.general_group)
        auto_row.addWidget(auto_label)
        self.auto_switch = SwitchWidget(checked=True, parent=self.general_group)
        self.auto_switch.toggled.connect(self._on_auto_download_toggled)
        auto_row.addWidget(self.auto_switch)
        auto_row.addStretch()
        general_layout.addLayout(auto_row)

        # 현재 설정값 UI 반영
        settings = get_current_settings()
        self.folder_input.setText(str(settings.download_dir))
        self.quality_combo.setCurrentText(settings.default_quality)
        self.ext_combo.setCurrentText(settings.file_extension)
        self.auto_switch.setChecked(settings.vod_auto_download)

        layout.addWidget(self.general_group)

        # 2. 네이버 / 치지직 쿠키 설정 그룹
        self.cookie_group = QGroupBox("네이버 / 치지직 쿠키 관리", self)
        group_layout = QVBoxLayout(self.cookie_group)
        group_layout.setContentsMargins(12, 14, 12, 14)
        group_layout.setSpacing(10)

        desc_label = QLabel(
            "성인 인증(19+) 및 비공개/구독 VOD 다운로드를 위해 네이버 로그인 쿠키가 필요합니다.",
            self.cookie_group,
        )
        desc_label.setStyleSheet("color: #9ca3af; font-size: 11px;")
        desc_label.setWordWrap(True)
        group_layout.addWidget(desc_label)

        # 상태 라벨
        self.status_label = QLabel("상태: 등록된 쿠키 없음", self.cookie_group)
        self.status_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        group_layout.addWidget(self.status_label)

        # 액션 버튼 행: [네이버 로그인] [보기 / 직접 입력] [불러오기 ▾] [내보내기] [초기화]
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.login_btn = QPushButton("네이버 로그인", self.cookie_group)
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.setStyleSheet(
            "QPushButton { background-color: #03c75a; color: white; border: none; "
            "border-radius: 4px; padding: 4px 12px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #02b150; }"
        )
        self.login_btn.clicked.connect(self._on_naver_login_clicked)
        btn_row.addWidget(self.login_btn)

        self.view_btn = QPushButton("보기 / 직접 입력", self.cookie_group)
        self.view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_btn.clicked.connect(self._on_view_clicked)
        btn_row.addWidget(self.view_btn)

        self.import_btn = QPushButton("파일 불러오기", self.cookie_group)
        self.import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_btn.clicked.connect(self._on_import_file)
        btn_row.addWidget(self.import_btn)

        self.export_btn = QPushButton("내보내기", self.cookie_group)
        self.export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_btn.clicked.connect(self._on_export_clicked)
        btn_row.addWidget(self.export_btn)

        self.clear_btn = QPushButton("초기화", self.cookie_group)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setStyleSheet("color: #ef4444;")
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        btn_row.addWidget(self.clear_btn)

        btn_row.addStretch()
        group_layout.addLayout(btn_row)

        layout.addWidget(self.cookie_group)
        layout.addStretch()

        # 하단 닫기 버튼
        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        self.close_btn = QPushButton("닫기", self)
        self.close_btn.clicked.connect(self.close)
        bottom_layout.addWidget(self.close_btn)
        layout.addLayout(bottom_layout)

    def refresh_status(self) -> None:
        """현재 쿠키 상태에 따라 라벨과 스타일을 갱신합니다."""
        from chzzk_downloader.core.cookie_manager import (
            SessionStatus,
            get_last_session_status,
        )

        status, _ = get_last_session_status()
        summary = get_cookie_status_summary()
        self.status_label.setText(f"상태: {summary}")

        if status == SessionStatus.EXPIRED:
            self.status_label.setStyleSheet(
                "color: #ef4444; font-size: 12px; font-weight: bold;"
            )
            self.export_btn.setEnabled(True)
            self.clear_btn.setEnabled(True)
        elif "확인" in summary or status == SessionStatus.VALID:
            self.status_label.setStyleSheet(
                "color: #10b981; font-size: 12px; font-weight: bold;"
            )
            self.export_btn.setEnabled(True)
            self.clear_btn.setEnabled(True)
        else:
            self.status_label.setStyleSheet(
                "color: #9ca3af; font-size: 12px; font-weight: bold;"
            )
            self.export_btn.setEnabled(False)
            self.clear_btn.setEnabled(False)

    def _on_naver_login_clicked(self) -> None:
        """내장 브라우저 네이버 로그인 창을 엽니다."""
        from chzzk_downloader.gui.naver_login_dialog import NaverLoginDialog

        self._login_dialog = NaverLoginDialog(self)
        self._login_dialog.login_success.connect(self._on_naver_login_success)
        self._login_dialog.exec()
        self._login_dialog.deleteLater()
        self._login_dialog = None

    def _on_naver_login_success(self, msg: str) -> None:
        """네이버 로그인 완료 시 상태를 갱신하고 변경 시그널을 방출합니다."""
        self.refresh_status()
        self.cookies_updated.emit()

    def _on_view_clicked(self) -> None:
        """쿠키 보기 및 직접 입력 모달 다이얼로그를 엽니다."""
        dialog = CookieViewerDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_status()
            self.cookies_updated.emit()

    def _on_import_file(self) -> None:
        """Netscape 형식의 쿠키 파일(*.txt)을 파일 탐색기에서 선택해 불러옵니다."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Netscape 쿠키 파일 선택",
            "",
            "Netscape HTTP Cookie Files (*.txt);;모든 파일 (*.*)",
        )
        if file_path:
            ok, msg = load_cookie_file(Path(file_path))
            if ok:
                QMessageBox.information(self, "불러오기 완료", msg)
                self.refresh_status()
                self.cookies_updated.emit()
            else:
                QMessageBox.warning(self, "불러오기 실패", msg)

    def _on_export_clicked(self) -> None:
        """현재 저장된 쿠키를 파일로 내보냅니다."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "쿠키 파일 내보내기",
            "cookies.txt",
            "Netscape HTTP Cookie Files (*.txt);;모든 파일 (*.*)",
        )
        if file_path:
            ok, msg = export_cookie_file(Path(file_path))
            if ok:
                QMessageBox.information(self, "내보내기 완료", msg)
            else:
                QMessageBox.warning(self, "내보내기 실패", msg)

    def _on_clear_clicked(self) -> None:
        """등록된 쿠키를 초기화합니다 (확인/취소, 확인 하이라이트)."""
        if ask_confirm_dialog(
            self,
            text="저장된 쿠키를 삭제하시겠습니까?",
            is_danger=True,
        ):
            ok, msg = clear_cookies()
            if ok:
                self.refresh_status()
                self.cookies_updated.emit()
                QMessageBox.information(
                    self, "초기화 완료", "등록된 쿠키가 삭제되었습니다."
                )
            else:
                QMessageBox.warning(self, "초기화 실패", msg)

    def _on_choose_folder(self) -> None:
        """폴더 아이콘 클릭 시 시스템 디렉터리 선택 창을 열어 경로를 지정합니다."""
        current_dir = self.folder_input.text() or str(Path.cwd())
        try:
            selected = QFileDialog.getExistingDirectory(
                self, "저장 폴더 선택", current_dir
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                "폴더 오류",
                f"폴더 선택 창을 여는 중 오류가 발생했습니다: {e}",
            )
            return

        if not selected:
            # 사용자가 탐색기를 취소하거나 닫은 경우 기존 경로 유지
            return

        try:
            ok, msg = update_current_settings(download_dir=selected)
            if ok:
                self.folder_input.setText(str(Path(selected).resolve()))
            else:
                QMessageBox.warning(self, "폴더 오류", msg)
        except Exception as e:
            QMessageBox.warning(
                self,
                "폴더 오류",
                f"경로 갱신 중 예외가 발생했습니다: {e}",
            )

    def _on_quality_changed(self, text: str) -> None:
        """기본 화질 콤보박스 변경 핸들러: 변경 즉시 영속화."""
        if text:
            update_current_settings(default_quality=text)

    def _on_ext_changed(self, text: str) -> None:
        """파일 확장자 콤보박스 변경 핸들러: 변경 즉시 영속화."""
        if text:
            update_current_settings(file_extension=text)

    def _on_auto_download_toggled(self, checked: bool) -> None:
        """VOD 자동 다운로드 토글 스위치 핸들러: 변경 즉시 영속화."""
        update_current_settings(vod_auto_download=checked)
