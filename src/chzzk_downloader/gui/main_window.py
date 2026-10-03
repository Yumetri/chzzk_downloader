"""메인 윈도우 모듈."""

import html
from pathlib import Path
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
from chzzk_downloader.core.errors import classify_error
from chzzk_downloader.core.task_manager import TaskManager
from chzzk_downloader.core.task_models import TaskProgress, TaskSpec, TaskStatus
from chzzk_downloader.core.url_parser import parse_chzzk_vod_url
from chzzk_downloader.core.ytdlp import VodInfo
from chzzk_downloader.gui.dialogs import ask_confirm_dialog
from chzzk_downloader.gui.task_card import TaskCardWidget
from chzzk_downloader.gui.toast import ToastType, ToastWidget
from chzzk_downloader.gui.workers import VodCheckWorker, VodDownloadWorker

_DETACHED_WORKERS: set[QThread] = set()


class TaskListWidget(QWidget):
    """작업 목록 및 빈 상태 안내를 관리하는 위젯."""

    request_open_settings = pyqtSignal()
    request_naver_login = pyqtSignal()
    download_blocked = pyqtSignal(str)
    card_download_requested = pyqtSignal(object, object)  # (TaskCardWidget, TaskSpec)
    card_stop_requested = pyqtSignal(str)  # (task_id)
    card_retry_requested = pyqtSignal(str)  # (task_id)
    card_complete_requested = pyqtSignal(str)  # (task_id)

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

    def find_task_card_by_id(self, task_id: str) -> TaskCardWidget | None:
        """주어진 task_id를 가진 작업 카드를 찾아 반환합니다."""
        for card in self.get_all_cards():
            if card.is_deleted or sip.isdeleted(card):
                continue
            if getattr(card, "task_id", None) == task_id:
                return card
        return None

    def has_task(self, video_no: str | None, raw_url: str) -> bool:
        """주어진 video_no 또는 raw_url을 가진 작업 카드가 이미 존재하는지 확인합니다."""
        return self.find_task_card(video_no, raw_url) is not None

    def remove_task_card(self, card: TaskCardWidget) -> None:
        """작업 카드를 UI 목록에서 안전하게 제거합니다."""
        if card.is_deleted or sip.isdeleted(card):
            return
        if hasattr(card, "close_info_window"):
            card.close_info_window()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item is not None and self.list_widget.itemWidget(item) is card:
                self.list_widget.takeItem(i)
                break
        card.deleteLater()
        self.refresh_state()

        main_win = self.window()
        if hasattr(main_win, "task_manager"):
            main_win.task_manager.remove_task(card.task_id)

    def add_task_card(self, card: TaskCardWidget) -> QListWidgetItem:
        """작업 카드를 목록 최상단에 추가하고 표시 상태를 갱신합니다."""
        item = QListWidgetItem()
        item.setSizeHint(card.sizeHint())
        self.list_widget.insertItem(0, item)
        self.list_widget.setItemWidget(item, card)

        def _on_delete() -> None:
            self.remove_task_card(card)

        card.delete_requested.connect(_on_delete)
        card.request_open_cookies.connect(self.request_open_settings.emit)
        card.request_naver_login.connect(self.request_naver_login.emit)
        card.download_blocked.connect(self.download_blocked.emit)

        if hasattr(card, "request_start_download"):
            card.request_start_download.connect(
                lambda spec, c=card: self.card_download_requested.emit(c, spec)
            )
        if hasattr(card, "request_stop_download"):
            card.request_stop_download.connect(self.card_stop_requested.emit)
        card.retry_requested.connect(self.card_retry_requested.emit)
        card.complete_requested.connect(self.card_complete_requested.emit)

        self.refresh_state()
        return item


class MainWindow(QMainWindow):
    """실행 가능한 최소 메인 창 (T0101, T0102)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("치지직 VOD 다운로더")
        self.resize(640, 480)

        self.task_manager = TaskManager(max_concurrent_vod=3)
        self._download_workers: dict[str, VodDownloadWorker] = {}
        self._pending_vod_starts: dict[str, TaskSpec] = {}
        self._init_task_manager()

        self._worker: VodCheckWorker | None = None
        self._recheck_workers: list[VodCheckWorker] = []
        self._url_context_menu: QMenu | None = None
        self.current_vod_info: VodInfo | None = None
        self._init_ui()

    def _init_task_manager(self) -> None:
        """TaskManager 시그널들을 MainWindow 슬롯에 바인딩합니다."""
        self.task_manager.signals.task_status_changed.connect(
            self._on_task_status_changed
        )
        self.task_manager.signals.task_completed.connect(self._on_task_completed)
        self.task_manager.signals.task_failed.connect(self._on_task_failed)
        self.task_manager.signals.task_removed.connect(self._on_task_removed)
        self.task_manager.signals.queue_updated.connect(self._on_queue_updated)
        self.task_manager.signals.task_progress_updated.connect(self._on_task_progress)

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
        self.task_list_widget.download_blocked.connect(self._on_download_blocked)
        self.task_list_widget.card_download_requested.connect(
            self._on_card_request_start_download
        )
        self.task_list_widget.card_stop_requested.connect(
            self._on_card_request_stop_download
        )
        self.task_list_widget.card_retry_requested.connect(
            self._on_card_retry_requested
        )
        self.task_list_widget.card_complete_requested.connect(
            self._on_card_complete_requested
        )
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
            try:
                self._worker.finished.disconnect()
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

        if hasattr(self, "_download_workers"):
            for worker in list(self._download_workers.values()):
                self._detach_download_worker(worker, disconnect_signals=True)
            self._download_workers.clear()

        if hasattr(self, "_settings_window") and self._settings_window is not None:
            self._settings_window.close()

        # 열려 있는 모든 작업 카드의 TaskInfoWindow 닫기
        for card in self.task_list_widget.get_all_cards():
            if hasattr(card, "_info_win") and card._info_win is not None:
                if not sip.isdeleted(card._info_win):
                    card._info_win.close()
                card._info_win = None

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
                    ("🍪", "transparent", self._on_settings_clicked, "쿠키 설정"),
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
            card.reset_for_redownload()
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

        def _on_vod_check_finished() -> None:
            if (
                not sip.isdeleted(self)
                and hasattr(self, "download_btn")
                and not sip.isdeleted(self.download_btn)
            ):
                self.download_btn.setEnabled(True)

        worker.finished.connect(_on_vod_check_finished)
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
            # 읽는 중(ANALYZING), 녹화 중(DOWNLOADING), 대기/준비 중(READY, QUEUED) 상태인 경우 즉시 거부 토스트 출력
            if existing_card.status in (
                TaskStatus.ANALYZING,
                TaskStatus.DOWNLOADING,
                TaskStatus.READY,
                TaskStatus.QUEUED,
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
                old_worker = self._download_workers.get(existing_card.task_id)
                if (
                    old_worker is not None
                    and old_worker.isRunning()
                    and old_worker.is_cancelled
                ):
                    self.toast.show_toast(
                        '<span style="color: #f59e0b; font-size: 14px; font-weight: bold; margin-right: 6px;">⚠️</span> '
                        '<span style="color: #ffffff;">이전 작업이 아직 정리 중입니다. 잠시 후 다시 시도해주세요.</span>',
                        ToastType.WARNING,
                        auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
                    )
                    return
                # 이전 세션 워커/스레드 및 파일 핸들 정리, 클린 리셋
                if hasattr(self, "task_manager"):
                    self.task_manager.reset_task(existing_card.task_id)
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
        safe_url = html.escape(raw_url)
        message = (
            f'<span style="color: #3b82f6; font-weight: bold; font-size: 14px;">+</span> '
            f'<span style="color: #ffffff;">{safe_url}</span>'
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

        classified = classify_error(msg=error_msg)
        if classified == TaskStatus.FAILED_LOGIN_REQUIRED:
            status = TaskStatus.FAILED_LOGIN_REQUIRED
            toast_msg = f"Login required; Please login\n{raw_url}"
        elif classified == TaskStatus.FAILED_DOWNLOAD:
            status = TaskStatus.FAILED_DOWNLOAD
            toast_msg = f"조회 실패: {error_msg}"
        else:
            status = TaskStatus.FAILED_INVALID
            toast_msg = f"Invalid: {raw_url}"

        card.set_failed(status, error_msg)

        self.toast.show_toast(
            toast_msg,
            ToastType.ERROR,
            auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
        )

    def _on_download_blocked(self, reason: str) -> None:
        """다운로드 시작 차단 시 경고 토스트를 표시합니다 (T0110)."""
        safe_reason = html.escape(reason)
        self.toast.show_toast(
            f'<span style="color: #f59e0b;">⚠️</span> {safe_reason}',
            ToastType.WARNING,
            auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
        )

    def _detach_download_worker(
        self, worker: VodDownloadWorker, disconnect_signals: bool = False
    ) -> None:
        """다운로드 워커를 안전하게 중지 및 분리하여 백그라운드에서 정리되도록 보존합니다."""
        if disconnect_signals:
            for sig in (
                worker.progress_updated,
                worker.download_finished,
                worker.download_failed,
                worker.download_stopped,
                worker.finished,
            ):
                try:
                    sig.disconnect()
                except Exception:
                    pass

        if worker.isRunning():
            worker.cancel()
            worker.setParent(None)
            _DETACHED_WORKERS.add(worker)
            worker.finished.connect(lambda ref=worker: _DETACHED_WORKERS.discard(ref))

    def _on_card_request_start_download(
        self, card: TaskCardWidget, spec: TaskSpec
    ) -> None:
        """카드의 다운로드 요청을 TaskManager에 등록합니다."""
        existing_worker = self._download_workers.get(spec.task_id)
        if (
            existing_worker is not None
            and existing_worker.isRunning()
            and existing_worker.is_cancelled
        ):
            self.toast.show_toast(
                '<span style="color: #f59e0b; font-size: 14px; font-weight: bold; margin-right: 6px;">⚠️</span> '
                '<span style="color: #ffffff;">이전 작업이 아직 정리 중입니다. 잠시 후 다시 시도해주세요.</span>',
                ToastType.WARNING,
                auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
            )
            return
        status = self.task_manager.add_task(spec)
        card.set_task_status(status)
        if status == TaskStatus.QUEUED:
            pos = self.task_manager.get_waiting_position(spec.task_id)
            card.set_waiting_position(pos)

    def _start_vod_download(self, task_id: str) -> None:
        """DOWNLOADING 상태인 작업에 대해 백그라운드 VodDownloadWorker를 구동합니다."""
        if self.task_manager.get_task_status(task_id) != TaskStatus.DOWNLOADING:
            return

        spec = self.task_manager.get_task_spec(task_id)
        if not spec:
            card = self.task_list_widget.find_task_card_by_id(task_id)
            if card is not None:
                spec = card.get_task_spec()
        if not spec:
            return

        existing_worker = self._download_workers.get(task_id)
        if existing_worker is not None and existing_worker.isRunning():
            self._pending_vod_starts[task_id] = spec
            self.toast.show_toast(
                '<span style="color: #f59e0b; font-size: 14px; font-weight: bold; margin-right: 6px;">⚠️</span> '
                '<span style="color: #ffffff;">이전 작업 정리 완료 후 자동으로 시작됩니다.</span>',
                ToastType.WARNING,
                auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
            )
            return

        worker = VodDownloadWorker(spec, parent=self)
        worker.progress_updated.connect(
            lambda p, tid=task_id, w=worker: self._on_worker_progress(w, tid, p)
        )
        worker.download_finished.connect(
            lambda tid, path, w=worker: self._on_worker_finished(w, tid, path)
        )
        worker.download_failed.connect(
            lambda tid, etype, msg, tb, w=worker: self._on_worker_failed(
                w, tid, etype, msg, tb
            )
        )
        worker.download_stopped.connect(
            lambda tid, w=worker: self._on_worker_stopped(w, tid)
        )
        worker.finished.connect(
            lambda tid=task_id, w=worker: self._cleanup_worker(tid, w)
        )

        self._download_workers[task_id] = worker
        worker.start()

    def _cleanup_worker(self, task_id: str, worker: VodDownloadWorker) -> None:
        """워커 종료 시 슬롯 반환을 확정하고 활성 워커 딕셔너리에서 안전하게 분리합니다."""
        if self._download_workers.get(task_id) is worker:
            self._download_workers.pop(task_id, None)

            pending_spec = self._pending_vod_starts.pop(task_id, None)

            # 아직 DOWNLOADING 상태인 경우 슬롯 회수 확정
            if self.task_manager.get_task_status(task_id) == TaskStatus.DOWNLOADING:
                if worker.is_cancelled:
                    self.task_manager.report_stopped(task_id)
                else:
                    self.task_manager.report_failed(
                        task_id,
                        "WorkerTerminated",
                        "워커 스레드가 비정상 종료되었습니다.",
                    )

            # 이전 워커 정리 중 대기 등록된 신규 작업이 있으면 바통을 이어받아 시작
            if pending_spec is not None:
                current_status = self.task_manager.get_task_status(task_id)
                if current_status in (
                    TaskStatus.STOPPED,
                    TaskStatus.FAILED_DOWNLOAD,
                    TaskStatus.FAILED_LOGIN_REQUIRED,
                ):
                    self.task_manager.retry_task(task_id)
                elif current_status == TaskStatus.DOWNLOADING:
                    self._start_vod_download(task_id)
        if not sip.isdeleted(worker):
            worker.setParent(None)

    def _on_worker_progress(
        self, worker: VodDownloadWorker, task_id: str, progress: TaskProgress
    ) -> None:
        """워커의 진행 상황을 TaskManager에 보고합니다 (UI 갱신은 TaskManager 100ms 스로틀링을 통해 단일화)."""
        if self._download_workers.get(task_id) is not worker:
            return
        self.task_manager.report_progress(task_id, progress)

    def _on_task_progress(self, task_id: str, progress: TaskProgress) -> None:
        """TaskManager로부터 진행률 보고를 수신하여 해당 카드 UI를 갱신합니다."""
        card = self.task_list_widget.find_task_card_by_id(task_id)
        if card is not None and not card.is_deleted and not sip.isdeleted(card):
            card.update_progress(progress)

    def _on_worker_finished(
        self, worker: VodDownloadWorker, task_id: str, final_file_path: str
    ) -> None:
        """워커 다운로드 성공 완료를 TaskManager에 통지합니다."""
        if self._download_workers.get(task_id) is not worker:
            return
        self.task_manager.report_completed(task_id, final_file_path)

    def _on_worker_failed(
        self,
        worker: VodDownloadWorker,
        task_id: str,
        err_type: str,
        msg: str,
        traceback_str: str,
    ) -> None:
        """워커 다운로드 실패를 TaskManager에 통지합니다."""
        if self._download_workers.get(task_id) is not worker:
            return
        self.task_manager.report_failed(task_id, err_type, msg, traceback_str)

    def _on_worker_stopped(self, worker: VodDownloadWorker, task_id: str) -> None:
        """워커 다운로드 중단 이벤트 수신 핸들러 (슬롯 반환은 worker.finished의 _cleanup_worker에서 수행)."""
        if self._download_workers.get(task_id) is not worker:
            return

    def _on_task_status_changed(
        self, task_id: str, old_status: TaskStatus, new_status: TaskStatus
    ) -> None:
        """TaskManager로부터 상태 전이 알림을 수신하여 해당 카드 UI를 갱신합니다."""
        current_status = self.task_manager.get_task_status(task_id)
        if current_status != new_status:
            return

        card = self.task_list_widget.find_task_card_by_id(task_id)
        if card is not None and not card.is_deleted and not sip.isdeleted(card):
            card.set_task_status(new_status)
            if new_status == TaskStatus.QUEUED:
                pos = self.task_manager.get_waiting_position(task_id)
                card.set_waiting_position(pos)
        if new_status == TaskStatus.DOWNLOADING:
            self._start_vod_download(task_id)

    def _on_task_completed(self, task_id: str, final_file_path: str) -> None:
        """TaskManager로부터 작업 완료 알림을 수신하여 카드를 완료 처리하고 완료 토스트를 노출합니다."""
        card = self.task_list_widget.find_task_card_by_id(task_id)
        if card is None or card.is_deleted or sip.isdeleted(card):
            return

        card.set_completed(final_file_path)

        file_name = Path(final_file_path).name if final_file_path else task_id
        safe_file_name = html.escape(file_name)
        toast_msg = (
            f'<span style="color: #10b981; font-weight: bold; font-size: 14px;">✓</span> '
            f'<span style="color: #ffffff;">{safe_file_name}</span>'
        )
        self.toast.show_toast(
            toast_msg,
            ToastType.SUCCESS,
            auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
        )

    def show_file_deleted_toast(self, name_or_url: str) -> None:
        """T08: 동영상 파일 삭제 시 반투명 알약형 삭제 토스트를 노출합니다 (2.5초 자동 소멸)."""
        safe_name = html.escape(name_or_url)
        toast_msg = (
            f'<span style="color: #ef4444; font-size: 14px;">🗑</span> '
            f'<span style="color: #ffffff;">{safe_name}</span>'
        )
        self.toast.show_toast(
            toast_msg,
            ToastType.ERROR,
            auto_dismiss_ms=2500,
        )

    def _on_task_failed(
        self, task_id: str, err_type: str, msg: str, traceback_str: str
    ) -> None:
        """TaskManager로부터 작업 실패 알림을 수신하여 상태 전이 및 사유별 토스트를 노출합니다."""
        card = self.task_list_widget.find_task_card_by_id(task_id)
        if card is None or card.is_deleted or sip.isdeleted(card):
            return

        failed_status = self.task_manager.get_task_status(task_id)
        if failed_status not in (
            TaskStatus.FAILED_LOGIN_REQUIRED,
            TaskStatus.FAILED_INVALID,
            TaskStatus.FAILED_DOWNLOAD,
        ):
            failed_status = classify_error(exc_type=err_type, msg=msg)

        if failed_status == TaskStatus.FAILED_LOGIN_REQUIRED:
            self.toast.show_action_toast(
                '<span style="color: #f59e0b; font-size: 14px; font-weight: bold; margin-right: 6px;">⚠️</span> '
                '<span style="color: #ffffff;">쿠키를 갱신하세요</span>',
                buttons=[
                    ("🍪", "transparent", self._on_settings_clicked, "쿠키 설정"),
                    ("N", "#03c75a", self._on_naver_login_clicked, "네이버 로그인"),
                ],
            )
        elif failed_status == TaskStatus.FAILED_INVALID:
            self.toast.show_toast(
                f"Invalid: {msg}",
                ToastType.ERROR,
                auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
            )
        else:
            self.toast.show_toast(
                f"다운로드 실패: {msg}",
                ToastType.ERROR,
                auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
            )

        card.set_failed(
            failed_status,
            msg,
            error_type=err_type,
            traceback_str=traceback_str,
        )

    def _on_card_request_stop_download(self, task_id: str) -> None:
        """카드의 중지 요청을 워커에 안전하게 전달합니다 (슬롯 반환은 워커 finished 시점에 수행)."""
        worker = self._download_workers.get(task_id)
        if worker is not None and worker.isRunning():
            worker.cancel()
        else:
            self.task_manager.cancel_task(task_id)

    def _on_card_retry_requested(self, task_id: str) -> None:
        """카드의 재시도 요청을 수신하여 TaskManager를 통해 작업 재개를 트리거합니다."""
        worker = self._download_workers.get(task_id)
        if worker is not None and worker.isRunning():
            spec = self.task_manager.get_task_spec(task_id)
            if spec is None:
                card = self.task_list_widget.find_task_card_by_id(task_id)
                if card is not None:
                    spec = card.get_task_spec()
            if spec is not None:
                self._pending_vod_starts[task_id] = spec
                self.toast.show_toast(
                    '<span style="color: #f59e0b; font-size: 14px; font-weight: bold; margin-right: 6px;">⚠️</span> '
                    '<span style="color: #ffffff;">이전 작업 정리 완료 후 자동으로 시작됩니다.</span>',
                    ToastType.WARNING,
                    auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
                )
            return

        spec = self.task_manager.get_task_spec(task_id)
        if spec is None:
            card = self.task_list_widget.find_task_card_by_id(task_id)
            if card is not None:
                spec = card.get_task_spec()
                self.task_manager.add_task(spec)

        self.task_manager.retry_task(task_id)

    def _on_card_complete_requested(self, task_id: str) -> None:
        """카드의 완료 확정 요청을 수신하여 유효 파일 검증 후 TaskManager를 통해 COMPLETED 상태로 확정합니다."""
        card = self.task_list_widget.find_task_card_by_id(task_id)
        if card is None:
            return

        target = card.final_file_path or card.target_path
        if not target:
            self.toast.show_toast(
                '<span style="color: #f59e0b;">⚠️</span> 완료 확정할 미디어 파일이 디스크에 존재하지 않습니다.',
                ToastType.WARNING,
                auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
            )
            return

        target_path = Path(target)
        try:
            if not target_path.is_file() or target_path.stat().st_size == 0:
                self.toast.show_toast(
                    '<span style="color: #f59e0b;">⚠️</span> 완료 확정할 미디어 파일이 디스크에 존재하지 않습니다.',
                    ToastType.WARNING,
                    auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
                )
                return
        except OSError:
            self.toast.show_toast(
                '<span style="color: #f59e0b;">⚠️</span> 완료 확정할 미디어 파일에 접근할 수 없습니다.',
                ToastType.WARNING,
                auto_dismiss_ms=SUCCESS_TOAST_DURATION_MS,
            )
            return

        self.task_manager.complete_task(task_id, str(target_path))

    def _on_task_removed(self, task_id: str) -> None:
        """TaskManager로부터 작업 제거 알림을 수신하여 목록에서 카드를 제거합니다."""
        worker = self._download_workers.get(task_id)
        if worker is not None and worker.isRunning():
            worker.cancel()
        else:
            self._download_workers.pop(task_id, None)
        card = self.task_list_widget.find_task_card_by_id(task_id)
        if card is not None and not card.is_deleted and not sip.isdeleted(card):
            self.task_list_widget.remove_task_card(card)

    def _on_queue_updated(
        self, running_vod: int, queued_vod: int, running_live: int
    ) -> None:
        """대기열 상태 변경 시 모든 대기 중인 카드의 순번을 갱신합니다."""
        for card in self.task_list_widget.get_all_cards():
            if (
                not card.is_deleted
                and not sip.isdeleted(card)
                and card.status == TaskStatus.QUEUED
            ):
                pos = self.task_manager.get_waiting_position(card.task_id)
                card.set_waiting_position(pos)
