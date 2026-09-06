"""메인 윈도우 모듈."""

from typing import Any

from PyQt6 import sip
from PyQt6.QtCore import QPoint, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QResizeEvent
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from chzzk_downloader.config import SUCCESS_TOAST_DURATION_MS
from chzzk_downloader.core.url_parser import parse_chzzk_vod_url
from chzzk_downloader.core.ytdlp import VodInfo
from chzzk_downloader.gui.dialogs import ask_confirm_dialog
from chzzk_downloader.gui.task_card import TaskCardWidget, TaskStatus
from chzzk_downloader.gui.toast import ToastType, ToastWidget
from chzzk_downloader.gui.workers import VodCheckWorker

_DETACHED_WORKERS: set[QThread] = set()


class TaskListWidget(QWidget):
    """작업 목록 및 빈 상태 안내를 관리하는 위젯."""

    request_open_settings = pyqtSignal()
    request_naver_login = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget(self)
        self.empty_label = QLabel("작업 없음", self)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: gray; font-size: 14px;")

        self.list_widget = QListWidget(self)
        self.list_widget.setStyleSheet(
            "QListWidget { background-color: transparent; border: none; outline: none; }"
            "QListWidget::item { background: transparent; border: none; margin-bottom: 6px; }"
        )

        self.stack.addWidget(self.empty_label)
        self.stack.addWidget(self.list_widget)
        self.stack.setCurrentWidget(self.empty_label)

        layout.addWidget(self.stack)

    def refresh_state(self) -> None:
        """아이템 유무에 따라 표시 위젯을 전환합니다."""
        if self.list_widget.count() == 0:
            self.stack.setCurrentWidget(self.empty_label)
        else:
            self.stack.setCurrentWidget(self.list_widget)

    def get_all_cards(self) -> list[TaskCardWidget]:
        """현재 목록에 등록되어 있는 모든 TaskCardWidget 목록을 반환합니다."""
        cards: list[TaskCardWidget] = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item is not None:
                widget = self.list_widget.itemWidget(item)
                if isinstance(widget, TaskCardWidget):
                    cards.append(widget)
        return cards

    def find_task_card(
        self, video_no: str | None, raw_url: str
    ) -> TaskCardWidget | None:
        """주어진 video_no 또는 raw_url을 가진 작업 카드를 찾아 반환합니다."""
        clean_raw = raw_url.strip()
        for card in self.get_all_cards():
            if card.is_deleted or sip.isdeleted(card):
                continue
            if video_no and card.video_no and card.video_no == video_no:
                return card
            if card.raw_url.strip() == clean_raw:
                return card
        return None

    def has_task(self, video_no: str | None, raw_url: str) -> bool:
        """주어진 video_no 또는 raw_url을 가진 작업 카드가 이미 존재하는지 확인합니다."""
        return self.find_task_card(video_no, raw_url) is not None

    def add_task_card(self, card: TaskCardWidget) -> QListWidgetItem:
        """작업 카드를 목록 최상단에 추가하고 표시 상태를 갱신합니다."""
        item = QListWidgetItem()
        item.setSizeHint(card.sizeHint())
        self.list_widget.insertItem(0, item)
        self.list_widget.setItemWidget(item, card)

        def _on_delete() -> None:
            row = self.list_widget.row(item)
            if row >= 0:
                self.list_widget.takeItem(row)
                card.deleteLater()
                self.refresh_state()

        card.delete_requested.connect(_on_delete)
        card.request_open_cookies.connect(self.request_open_settings.emit)
        card.request_naver_login.connect(self.request_naver_login.emit)
        self.refresh_state()
        return item


class MainWindow(QMainWindow):
    """실행 가능한 최소 메인 창 (T0101, T0102)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("치지직 VOD 다운로더")
        self.resize(640, 480)

        self._worker: VodCheckWorker | None = None
        self._recheck_workers: list[VodCheckWorker] = []
        self._url_context_menu: QMenu | None = None
        self.current_vod_info: VodInfo | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. 상단 영역: 설정 버튼
        header_layout = QHBoxLayout()
        header_layout.addStretch()
        self.settings_btn = QPushButton("설정", self)
        self.settings_btn.clicked.connect(self._on_settings_clicked)
        header_layout.addWidget(self.settings_btn)
        main_layout.addLayout(header_layout)

        # 2. URL 입력칸 및 다운로드 버튼 (수평 배치: [붙여넣기] [URL 입력칸] [다운로드])
        input_layout = QHBoxLayout()

        self.paste_btn = QPushButton("📋", self)
        self.paste_btn.setToolTip("붙여넣기")
        self.paste_btn.clicked.connect(self._on_paste_clicked)

        self.url_input = QLineEdit(self)
        self.url_input.setPlaceholderText("치지직 VOD URL을 입력하세요")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.url_input.customContextMenuRequested.connect(self._show_url_context_menu)

        self.download_btn = QPushButton("다운로드", self)
        self.download_btn.clicked.connect(self._on_download_clicked)
        self.url_input.returnPressed.connect(self.download_btn.click)

        input_layout.addWidget(self.paste_btn)
        input_layout.addWidget(self.url_input)
        input_layout.addWidget(self.download_btn)
        main_layout.addLayout(input_layout)

        # 3. 작업 목록 영역 (URL 입력칸 하단)
        self.task_list_widget = TaskListWidget(self)
        self.task_list_widget.request_open_settings.connect(self._on_settings_clicked)
        self.task_list_widget.request_naver_login.connect(self._on_naver_login_clicked)
        self.task_list = self.task_list_widget.list_widget
        self.empty_label = self.task_list_widget.empty_label
        main_layout.addWidget(self.task_list_widget)

        # 4. 오버레이 토스트 위젯
        self.toast = ToastWidget(self)

        # 5. 세션 검증 비동기 작업자 및 앱 시작 시 검증 트리거 (T0107)
        self._cookie_verify_worker: Any = None
        self._check_cookie_session_on_startup()

    def resizeEvent(self, event: QResizeEvent | None) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast.reposition()

    def closeEvent(self, event: QCloseEvent | None) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            try:
                self._worker.finished_success.disconnect()
            except Exception:
                pass
            try:
                self._worker.finished_failed.disconnect()
            except Exception:
                pass
            self._worker.setParent(None)
            self._worker.quit()
            self._worker.wait(100)
            if self._worker.isRunning():
                w_ref = self._worker
                w_ref.finished.connect(lambda ref=w_ref: _DETACHED_WORKERS.discard(ref))
                _DETACHED_WORKERS.add(w_ref)
            self._worker = None

        for w in list(self._recheck_workers):
            if w.isRunning():
                try:
                    w.finished_success.disconnect()
                except Exception:
                    pass
                try:
                    w.finished_failed.disconnect()
                except Exception:
                    pass
                w.setParent(None)
                w.quit()
                w.wait(100)
                if w.isRunning():
                    rw_ref = w
                    rw_ref.finished.connect(
                        lambda ref=rw_ref: _DETACHED_WORKERS.discard(ref)
                    )
                    _DETACHED_WORKERS.add(rw_ref)
        self._recheck_workers.clear()

        if (
            hasattr(self, "_cookie_verify_worker")
            and self._cookie_verify_worker is not None
            and self._cookie_verify_worker.isRunning()
        ):
            try:
                self._cookie_verify_worker.finished_verification.disconnect()
            except Exception:
                pass
            self._cookie_verify_worker.setParent(None)
            self._cookie_verify_worker.quit()
            self._cookie_verify_worker.wait(100)
            if self._cookie_verify_worker.isRunning():
                vw_ref = self._cookie_verify_worker
                vw_ref.finished.connect(
                    lambda ref=vw_ref: _DETACHED_WORKERS.discard(ref)
                )
                _DETACHED_WORKERS.add(vw_ref)
            self._cookie_verify_worker = None

        if hasattr(self, "_settings_window") and self._settings_window is not None:
            self._settings_window.close()
        super().closeEvent(event)

    def _check_cookie_session_on_startup(self) -> None:
        """앱 시작 시 저장된 쿠키가 존재하면 백그라운드 1회 세션 검증을 수행합니다 (T0107)."""
        from chzzk_downloader.core.cookie_manager import has_valid_cookies

        if not has_valid_cookies():
            return

        from chzzk_downloader.gui.workers import CookieVerifyWorker

        self._cookie_verify_worker = CookieVerifyWorker(timeout=3.0, parent=None)
        self._cookie_verify_worker.finished_verification.connect(
            self._on_cookie_session_verified
        )
        self._cookie_verify_worker.start()

    def _on_cookie_session_verified(self, status: Any, msg: str) -> None:
        """세션 검증 완료 핸들러 (정상 시 침묵, 만료 시 액션 토스트 노출)."""
        from chzzk_downloader.core.cookie_manager import SessionStatus

        if hasattr(self, "_settings_window") and self._settings_window is not None:
            self._settings_window.refresh_status()

        if status == SessionStatus.EXPIRED:
            # 경고 아이콘 + 간소화된 문구 + 컴팩트 아이콘 버튼 (호버 시 툴팁)
            self.toast.show_action_toast(
                '<span style="color: #f59e0b; font-size: 14px; font-weight: bold; margin-right: 6px;">⚠️</span> '
                '<span style="color: #ffffff;">쿠키를 갱신하세요</span>',
                buttons=[
                    ("🍪", "#3b82f6", self._on_settings_clicked, "쿠키 설정"),
                    ("N", "#03c75a", self._on_naver_login_clicked, "네이버 로그인"),
                ],
            )

    def _on_naver_login_clicked(self) -> None:
        """네이버 로그인 버튼 클릭 시 내장 브라우저 로그인 창을 엽니다."""
        from chzzk_downloader.gui.naver_login_dialog import NaverLoginDialog

        self._login_dialog = NaverLoginDialog(self)
        self._login_dialog.login_success.connect(self._on_naver_login_success)
        self._login_dialog.exec()
        self._login_dialog.deleteLater()
        self._login_dialog = None

    def _on_naver_login_success(self, msg: str) -> None:
        """네이버 로그인 완료 시 토스트 안내, 설정창 갱신 및 실패 카드 자동 재분석."""
        self.toast.show_toast(
            "네이버 로그인이 완료되었습니다.",
            ToastType.SUCCESS,
            auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
        )
        if hasattr(self, "_settings_window") and self._settings_window is not None:
            self._settings_window.refresh_status()
        self._on_cookies_updated()

    def _on_settings_clicked(self) -> None:
        """설정 버튼 또는 카드 내 쿠키 설정 클릭 핸들러 (Modeless 설정 창 오픈)."""
        from chzzk_downloader.gui.settings_window import SettingsWindow

        if not hasattr(self, "_settings_window") or self._settings_window is None:
            self._settings_window = SettingsWindow(self)
            self._settings_window.cookies_updated.connect(self._on_cookies_updated)
        self._settings_window.refresh_status()
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _on_cookies_updated(self) -> None:
        """쿠키 저장/불러오기 시 로그인 필요 실패 카드 자동 재분석 (T0106 옵션 A: 불필요한 토스트 없이 침묵 자동 재분석)."""
        from chzzk_downloader.core.cookie_manager import has_valid_cookies

        if not has_valid_cookies():
            return

        failed_cards = [
            c
            for c in self.task_list_widget.get_all_cards()
            if c.status == TaskStatus.FAILED_LOGIN_REQUIRED and not c.is_deleted
        ]
        if not failed_cards:
            return

        for card in failed_cards:
            card.status = TaskStatus.ANALYZING
            card._update_display()
            card._apply_style()
            worker = VodCheckWorker(card.video_no or card.raw_url, parent=None)
            self._recheck_workers.append(worker)

            def _on_success(
                info: Any, c: TaskCardWidget = card, w: VodCheckWorker = worker
            ) -> None:
                if w in self._recheck_workers:
                    self._recheck_workers.remove(w)
                self._on_vod_check_success(info, c)

            def _on_failed(
                err: str,
                c: TaskCardWidget = card,
                u: str = card.raw_url,
                w: VodCheckWorker = worker,
            ) -> None:
                if w in self._recheck_workers:
                    self._recheck_workers.remove(w)
                self._on_vod_check_failed(err, c, u)

            worker.finished_success.connect(_on_success)
            worker.finished_failed.connect(_on_failed)
            worker.start()

    def _on_paste_clicked(self) -> None:
        """붙여넣기 버튼 클릭 핸들러: 클립보드 텍스트를 URL 입력칸에 설정."""
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            text = clipboard.text()
            if text:
                self.url_input.setText(text)

    def _create_url_context_menu(self) -> QMenu:
        """URL 입력칸의 우클릭 컨텍스트 메뉴(non-modal)를 생성합니다."""
        menu = QMenu(self.url_input)

        undo_action = QAction("실행 취소", menu)
        undo_action.triggered.connect(self.url_input.undo)
        undo_action.setEnabled(self.url_input.isUndoAvailable())
        menu.addAction(undo_action)

        redo_action = QAction("다시 실행", menu)
        redo_action.triggered.connect(self.url_input.redo)
        redo_action.setEnabled(self.url_input.isRedoAvailable())
        menu.addAction(redo_action)

        menu.addSeparator()

        cut_action = QAction("잘라내기", menu)
        cut_action.triggered.connect(self.url_input.cut)
        cut_action.setEnabled(self.url_input.hasSelectedText())
        menu.addAction(cut_action)

        copy_action = QAction("복사", menu)
        copy_action.triggered.connect(self.url_input.copy)
        copy_action.setEnabled(self.url_input.hasSelectedText())
        menu.addAction(copy_action)

        clipboard = QApplication.clipboard()
        has_clip = bool(clipboard is not None and clipboard.text())

        paste_action = QAction("붙여넣기", menu)
        paste_action.triggered.connect(self.url_input.paste)
        paste_action.setEnabled(has_clip)
        menu.addAction(paste_action)

        paste_download_action = QAction("붙여넣고 다운로드", menu)
        paste_download_action.triggered.connect(self._on_paste_and_download)
        paste_download_action.setEnabled(has_clip)
        menu.addAction(paste_download_action)

        delete_action = QAction("삭제", menu)
        delete_action.triggered.connect(self.url_input.del_)
        delete_action.setEnabled(self.url_input.hasSelectedText())
        menu.addAction(delete_action)

        menu.addSeparator()

        select_all_action = QAction("모두 선택", menu)
        select_all_action.triggered.connect(self.url_input.selectAll)
        select_all_action.setEnabled(bool(self.url_input.text()))
        menu.addAction(select_all_action)

        return menu

    def _show_url_context_menu(self, pos: QPoint) -> None:
        """URL 입력칸 우클릭 시 non-modal로 컨텍스트 메뉴를 띄웁니다."""
        self._url_context_menu = self._create_url_context_menu()
        global_pos = self.url_input.mapToGlobal(pos)
        self._url_context_menu.popup(global_pos)

    def _on_paste_and_download(self) -> None:
        """클립보드 내용을 붙여넣고 즉시 다운로드 버튼을 클릭합니다."""
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            text = clipboard.text()
            if text:
                self.url_input.setText(text)
                self.download_btn.click()

    def _start_vod_check(self, card: TaskCardWidget, video_no: str) -> None:
        """지정된 카드에 대해 VOD 메타데이터 비동기 조회를 시작합니다."""
        self.download_btn.setEnabled(False)
        worker = VodCheckWorker(video_no, parent=None)
        worker.finished_success.connect(
            lambda info, c=card: self._on_vod_check_success(info, c)
        )
        worker.finished_failed.connect(
            lambda err, c=card, u=card.raw_url: self._on_vod_check_failed(err, c, u)
        )
        worker.finished.connect(lambda: self.download_btn.setEnabled(True))
        self._worker = worker
        worker.start()

    def _confirm_redownload_dialog(self) -> bool:
        """동일 VOD 재다운로드 확인 모달을 띄우고 승인 여부를 반환합니다 (확인/취소, 확인 하이라이트)."""
        return ask_confirm_dialog(
            parent=self,
            text="이미 추가한 작업입니다. 다시 다운로드하시겠습니까?",
        )

    def _on_download_clicked(self) -> None:
        """다운로드 버튼 클릭 핸들러 (T0104, T0109)."""
        # 새로운 요청 시작 시 기존 토스트 즉시 닫기
        self.toast.dismiss()

        raw_url = self.url_input.text().strip()
        if not raw_url:
            # 빈 입력일 때는 검증 및 토스트 노출 없이 무시
            return

        # 어떠한 방법으로든 다운로드 동작이 트리거되면 URL 입력칸 즉시 비우기
        self.url_input.clear()

        video_no = parse_chzzk_vod_url(raw_url)

        # 동일 작업 재다운로드 확인 및 충돌 방어 (T0109)
        existing_card = self.task_list_widget.find_task_card(video_no, raw_url)
        if existing_card is not None:
            # 읽는 중(ANALYZING), 녹화 중(DOWNLOADING), 대기 중(READY) 상태인 경우 즉시 거부 토스트 출력
            if existing_card.status in (
                TaskStatus.ANALYZING,
                TaskStatus.DOWNLOADING,
                TaskStatus.READY,
            ):
                self.toast.show_toast(
                    '<span style="color: #f59e0b; font-size: 14px; font-weight: bold; margin-right: 6px;">⚠️</span> '
                    '<span style="color: #ffffff;">이미 추가한 작업입니다.</span>',
                    ToastType.WARNING,
                    auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
                )
                return

            # 중지(STOPPED) 또는 실패 등 완결 상태인 경우 재다운로드 확인 모달
            if self._confirm_redownload_dialog():
                # 이전 세션 워커/스레드 및 파일 핸들 정리, 클린 리셋
                existing_card.reset_for_redownload()
                if video_no:
                    self._start_vod_check(existing_card, video_no)
                else:
                    existing_card.set_failed(TaskStatus.FAILED_INVALID, "Invalid URL")
            return

        if not video_no:
            # 유효하지 않은 URL: 작업 목록에 빨간색 실패 카드 즉시 추가
            card = TaskCardWidget(
                raw_url=raw_url,
                status=TaskStatus.FAILED_INVALID,
                parent=self,
            )
            self.task_list_widget.add_task_card(card)

            # 실패 토스트: Invalid: {URL}, 설정 시간(2초) 후 자동 소멸
            self.toast.show_toast(
                f"Invalid: {raw_url}",
                ToastType.ERROR,
                auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
            )
            return

        # 정상 치지직 VOD URL: 작업 목록에 분석 중 카드 즉시 추가
        card = TaskCardWidget(
            raw_url=raw_url,
            status=TaskStatus.ANALYZING,
            parent=self,
        )
        self.task_list_widget.add_task_card(card)

        # 정상 요청 시: 반투명 검은색 오버레이에 +(파란색) [URL(흰색)] 토스트 노출 후 2초 뒤 자동 소멸
        message = (
            f'<span style="color: #3b82f6; font-weight: bold; font-size: 14px;">+</span> '
            f'<span style="color: #ffffff;">{raw_url}</span>'
        )
        self.toast.show_toast(
            message,
            ToastType.SUCCESS,
            auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
        )

        self._start_vod_check(card, video_no)

    def _on_vod_check_success(
        self, info: VodInfo, card: TaskCardWidget | None = None
    ) -> None:
        """VOD 정보 조회 성공 처리: 해당 카드에 메타데이터 반영 및 자동 다운로드 분기."""
        self.current_vod_info = info
        if (
            card is None
            or card.is_deleted
            or sip.isdeleted(card)
            or card not in self.task_list_widget.get_all_cards()
        ):
            return
        card.update_with_vod_info(info)

        # VOD 자동 다운로드 분기 (T0109)
        from chzzk_downloader.core.settings_manager import get_current_settings

        settings = get_current_settings()
        if settings.vod_auto_download:
            card.trigger_start_download()

    def _on_vod_check_failed(
        self,
        error_msg: str,
        card: TaskCardWidget | None = None,
        raw_url: str = "",
    ) -> None:
        """VOD 정보 조회 실패 시 카드 상태 갱신 및 동일 문구의 실패 토스트(2초 자동 소멸)를 표시합니다."""
        if (
            card is None
            or card.is_deleted
            or sip.isdeleted(card)
            or card not in self.task_list_widget.get_all_cards()
        ):
            return

        err_lower = error_msg.lower()
        if (
            "login" in err_lower
            or "로그인" in err_lower
            or "인증" in err_lower
            or "adult" in err_lower
            or "19" in err_lower
            or "401" in err_lower
            or "unauthorized" in err_lower
            or "403" in err_lower
            or "forbidden" in err_lower
        ):
            status = TaskStatus.FAILED_LOGIN_REQUIRED
            toast_msg = f"Login required; Please login\n{raw_url}"
        else:
            status = TaskStatus.FAILED_INVALID
            toast_msg = f"Invalid: {raw_url}"

        card.set_failed(status, error_msg)

        self.toast.show_toast(
            toast_msg,
            ToastType.ERROR,
            auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
        )
