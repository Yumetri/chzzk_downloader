"""UI 피드백(모달 및 토스트) 인터랙티브 쇼케이스 도구.

개발자가 프로그램의 모든 모달 대화상자와 토스트 알림을 한 자리에서 직접 띄워보며
디자인, 여백, 폰트, 문체, 하이라이트 및 버튼 인터랙션을 즉각 검증할 수 있는 개발용 도구입니다.

실행 방법:
    uv run python -m chzzk_downloader.gui.feedback_showcase
또는
    uv run python tools/preview_ui_feedbacks.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from chzzk_downloader.core.filename_generator import generate_vod_filename
from chzzk_downloader.core.task_models import TaskProgress, TaskStatus
from chzzk_downloader.core.ytdlp import VodFormatInfo, VodInfo
from chzzk_downloader.gui.dialogs import ask_confirm_dialog
from chzzk_downloader.gui.task_card import TaskCardWidget
from chzzk_downloader.gui.toast import ToastType, ToastWidget


class FeedbackShowcaseWindow(QMainWindow):
    """모달, 토스트 및 작업 카드를 한눈에 확인하고 테스트할 수 있는 프리뷰어 창."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(
            "치지직 다운로더 - UI 피드백 쇼케이스 (모달·토스트·작업카드 갤러리)"
        )
        self.resize(920, 780)

        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(10)

        # 상단 탭 위젯 (탭 1: 모달 & 토스트 / 탭 2: 작업 목록 카드 갤러리)
        self.tabs = QTabWidget(self)
        self.tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #374151; border-radius: 4px; background-color: #1f2937; }"
            "QTabBar::tab { background: #374151; color: #9ca3af; padding: 8px 16px; font-weight: bold; border-top-left-radius: 4px; border-top-right-radius: 4px; }"
            "QTabBar::tab:selected { background: #1f2937; color: #ffffff; border-bottom: 2px solid #3b82f6; }"
        )

        # 탭 1: 모달 & 토스트 갤러리
        modal_toast_tab = QWidget()
        mt_layout = QVBoxLayout(modal_toast_tab)
        mt_layout.setContentsMargins(12, 12, 12, 12)
        mt_layout.setSpacing(12)

        header_label = QLabel(
            "🎨 UI 피드백 쇼케이스\n버튼을 클릭하여 각 모달 대화상자와 토스트의 문체, 디자인, 버튼 하이라이트를 즉각 확인하세요.",
            modal_toast_tab,
        )
        header_label.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #f3f4f6;"
        )
        mt_layout.addWidget(header_label)

        # 본문 좌/우 2열 레이아웃
        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(16)

        # 좌측: 토스트 테스트 영역
        toast_group = QGroupBox("🍞 토스트 알림 (Toast Notifications)", modal_toast_tab)
        toast_group.setStyleSheet("font-weight: bold; font-size: 13px; color: #f3f4f6;")
        toast_layout = QVBoxLayout(toast_group)
        toast_layout.setSpacing(8)

        self._add_btn(
            toast_layout,
            "[T01] URL 추가 토스트 (한 줄 URL)",
            self._demo_toast_add_url,
            "#2563eb",
        )
        self._add_btn(
            toast_layout,
            "[T02] 진행중 중복 거부 (⚠️ 경고 아이콘)",
            self._demo_toast_duplicate_rejected,
            "#d97706",
        )
        self._add_btn(
            toast_layout,
            "[T03] 지원하지 않는 URL (Invalid)",
            self._demo_toast_unsupported_url,
            "#dc2626",
        )
        self._add_btn(
            toast_layout,
            "[T04] VOD 확인 실패 (Invalid)",
            self._demo_toast_vod_check_failed,
            "#dc2626",
        )
        self._add_btn(
            toast_layout,
            "[T04] 로그인 필요 실패 (줄바꿈 포맷)",
            self._demo_toast_login_required,
            "#dc2626",
        )
        self._add_btn(
            toast_layout,
            "[T05] 쿠키 만료 경고 (쿠키를 갱신하세요, 🍪/N)",
            self._demo_toast_cookie_expired_action,
            "#d97706",
        )
        self._add_btn(
            toast_layout,
            "[T06] FFmpeg 미가용 경고 (⚠️ 경고 아이콘)",
            self._demo_toast_ffmpeg_unavailable,
            "#d97706",
        )
        self._add_btn(
            toast_layout,
            "[T07] 다운로드 완료 성공 (✓ 초록 체크, 사진 3 규격)",
            self._demo_toast_download_completed,
            "#059669",
        )
        self._add_btn(
            toast_layout,
            "[T08] 동영상 파일 삭제 (🗑 빨간 휴지통, 사진 규격)",
            self._demo_toast_file_deleted,
            "#dc2626",
        )
        toast_layout.addStretch()
        columns_layout.addWidget(toast_group, 1)

        # 우측: 모달 대화상자 테스트 영역
        modal_group = QGroupBox("💬 모달 대화상자 (Modal Dialogs)", modal_toast_tab)
        modal_group.setStyleSheet("font-weight: bold; font-size: 13px; color: #f3f4f6;")
        modal_layout = QVBoxLayout(modal_group)
        modal_layout.setSpacing(8)

        self._add_btn(
            modal_layout,
            "[M01] 다운로드 중지 확인 모달 (확인 하이라이트)",
            self._demo_modal_stop_download,
            "#1d4ed8",
        )
        self._add_btn(
            modal_layout,
            "[M02] 작업 재다운로드 확인 모달 (확인 하이라이트)",
            self._demo_modal_redownload_duplicate,
            "#1d4ed8",
        )
        self._add_btn(
            modal_layout,
            "[M03] 쿠키 초기화 확인 모달 (Danger 빨간 하이라이트)",
            self._demo_modal_clear_cookie,
            "#b91c1c",
        )
        self._add_btn(
            modal_layout,
            "[M04] 파일 중복 충돌 선택 모달 (간소화 문구)",
            self._demo_modal_file_conflict,
            "#4b5563",
        )
        self._add_btn(
            modal_layout,
            "[M05/M06] 쿠키 불러오기/내보내기 완료 안내 모달",
            self._demo_modal_cookie_info,
            "#4b5563",
        )
        self._add_btn(
            modal_layout,
            "[M07] 폴더 권한 오류 경고 모달",
            self._demo_modal_folder_error,
            "#b45309",
        )
        self._add_btn(
            modal_layout,
            "[M08] 외부 링크 이동 확인 모달 (치지직 뱃지 클릭)",
            self._demo_modal_external_link,
            "#1d4ed8",
        )
        self._add_btn(
            modal_layout,
            "[M09] FFmpeg 실행 파일 오류 경고 모달",
            self._demo_modal_ffmpeg_error,
            "#b45309",
        )
        self._add_btn(
            modal_layout,
            "[M10] 파일 삭제 확인 모달 (Danger 빨간 하이라이트)",
            self._demo_modal_delete_file,
            "#b91c1c",
        )
        modal_layout.addStretch()

        columns_layout.addWidget(modal_group, 1)

        mt_layout.addLayout(columns_layout, 1)
        self.tabs.addTab(modal_toast_tab, "🍞 토스트 & 💬 모달 갤러리")

        # 탭 2: 작업 목록 카드 프리뷰
        self.card_tab = self._create_cards_tab()
        self.tabs.addTab(self.card_tab, "🎴 작업 목록 카드 갤러리 (9대 상태)")

        root_layout.addWidget(self.tabs, 1)

        # 하단: 결과 로그 콘솔
        log_group = QGroupBox("📋 피드백 실행 로그 및 결과", self)
        log_group.setStyleSheet("color: #f3f4f6; font-size: 12px;")
        log_layout = QVBoxLayout(log_group)
        self.log_edit = QTextEdit(self)
        self.log_edit.setReadOnly(True)
        self.log_edit.setFixedHeight(100)
        self.log_edit.setStyleSheet(
            "background-color: #111827; color: #10b981; font-family: monospace; font-size: 12px;"
        )
        log_layout.addWidget(self.log_edit)
        root_layout.addWidget(log_group)

        # 토스트 위젯 오버레이 탑재
        self.toast = ToastWidget(self)
        self._log(
            "쇼케이스가 준비되었습니다. 원하는 토스트, 모달 또는 작업 카드 버튼을 클릭하세요."
        )

    def _add_btn(
        self,
        layout: QVBoxLayout,
        text: str,
        slot: Any,
        bg_color: str = "#374151",
    ) -> QPushButton:
        btn = QPushButton(text, self)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {bg_color}; color: white; border: none; "
            f"border-radius: 6px; padding: 10px 14px; font-size: 12px; text-align: left; }}"
            f"QPushButton:hover {{ background-color: #4b5563; }}"
        )
        btn.clicked.connect(slot)
        layout.addWidget(btn)
        return btn

    def _log(self, msg: str) -> None:
        self.log_edit.append(f"• {msg}")

    # --- 토스트 데모 메서드 ---
    def _demo_toast_add_url(self) -> None:
        self._log("[T01] URL 추가 토스트 호출 (검은 배경, 한 줄 URL)")
        msg = (
            '<span style="color: #3b82f6; font-weight: bold; font-size: 14px;">+</span> '
            '<span style="color: #ffffff;">https://chzzk.naver.com/video/15016450</span>'
        )
        self.toast.show_toast(msg, ToastType.SUCCESS, auto_dismiss_ms=2000)

    def _demo_toast_reanalyze_success(self) -> None:
        self._log(
            "[T02] 쿠키 재분석 토스트는 백그라운드 자동 재분석으로 전환되어 침묵 처리됩니다."
        )

    def _demo_toast_duplicate_rejected(self) -> None:
        self._log("[T02] 진행중 중복 거부 토스트 호출 (⚠️ 경고 아이콘)")
        msg = (
            '<span style="color: #f59e0b; font-size: 14px; font-weight: bold; margin-right: 6px;">⚠️</span> '
            '<span style="color: #ffffff;">이미 추가한 작업입니다.</span>'
        )
        self.toast.show_toast(
            msg,
            ToastType.WARNING,
            auto_dismiss_ms=2000,
        )

    def _demo_toast_unsupported_url(self) -> None:
        self._log("[T03] 지원하지 않는 URL 실패 토스트 (Invalid)")
        self.toast.show_toast(
            "Invalid: https://invalid-url.com/vod/9999",
            ToastType.ERROR,
            auto_dismiss_ms=2000,
        )

    def _demo_toast_vod_check_failed(self) -> None:
        self._log("[T04] VOD 확인 실패 토스트 (Invalid)")
        self.toast.show_toast(
            "Invalid: https://chzzk.naver.com/video/40404040",
            ToastType.ERROR,
            auto_dismiss_ms=2000,
        )

    def _demo_toast_login_required(self) -> None:
        self._log("[T04] 로그인 필요 실패 토스트 (줄바꿈 포맷)")
        self.toast.show_toast(
            "Login required; Please login\nhttps://chzzk.naver.com/video/19000000",
            ToastType.ERROR,
            auto_dismiss_ms=2000,
        )

    def _demo_toast_cookie_expired_action(self) -> None:
        self._log(
            "[T05] 쿠키 만료 경고 액션 토스트 호출 (쿠키를 갱신하세요, 🍪/N 아이콘)"
        )
        msg = (
            '<span style="color: #f59e0b; font-size: 14px; font-weight: bold; margin-right: 6px;">⚠️</span> '
            '<span style="color: #ffffff;">쿠키를 갱신하세요</span>'
        )
        self.toast.show_action_toast(
            msg,
            buttons=[
                (
                    "🍪",
                    "#3b82f6",
                    lambda: self._log("액션 토스트: [🍪 쿠키 설정] 클릭됨"),
                    "쿠키 설정",
                ),
                (
                    "N",
                    "#03c75a",
                    lambda: self._log("액션 토스트: [N 네이버 로그인] 클릭됨"),
                    "네이버 로그인",
                ),
            ],
        )

    def _demo_toast_ffmpeg_unavailable(self) -> None:
        self._log("[T06] FFmpeg 미가용 경고 토스트 호출")
        self.toast.show_toast(
            '<span style="color: #f59e0b;">⚠️</span> FFmpeg를 사용할 수 없습니다. 환경설정에서 FFmpeg를 설정해주세요.',
            ToastType.WARNING,
            auto_dismiss_ms=2000,
        )

    def _demo_toast_download_completed(self) -> None:
        vod_sample = VodInfo(
            video_no="15033444",
            video_title="김나성박이 (8STXaDJBI1)",
            channel_name="김나성",
            duration=26,
        )
        fn = generate_vod_filename(vod_sample, ext=".mp4")
        self._log(f"[T07] 다운로드 완료 성공 토스트 호출 (✓ 초록 체크, 파일명: {fn})")
        msg = (
            '<span style="color: #10b981; font-weight: bold; font-size: 14px;">✓</span> '
            f'<span style="color: #ffffff;">{fn}</span>'
        )
        self.toast.show_toast(
            msg,
            ToastType.SUCCESS,
            auto_dismiss_ms=2000,
        )

    def _demo_toast_file_deleted(self) -> None:
        vod_sample = VodInfo(
            video_no="15033444",
            video_title="김나성박이 (8STXaDJBI1)",
            channel_name="김나성",
            duration=26,
        )
        fn = generate_vod_filename(vod_sample, ext=".mp4")
        self._log(f"[T08] 동영상 파일 삭제 토스트 호출 (🗑 빨간 휴지통, 파일명: {fn})")
        msg = (
            '<span style="color: #ef4444; font-size: 14px;">🗑</span> '
            f'<span style="color: #ffffff;">{fn}</span>'
        )
        self.toast.show_toast(
            msg,
            ToastType.ERROR,
            auto_dismiss_ms=2500,
        )

    # --- 모달 데모 메서드 ---
    def _demo_modal_stop_download(self) -> None:
        self._log("[M01] 다운로드 중지 확인 모달 호출 대기...")
        ok = ask_confirm_dialog(
            parent=self,
            text="정말 중지하시겠습니까?",
        )
        self._log(
            f"[M01] 다운로드 중지 결과: {'[확인] 승인됨 (다운로드 중단)' if ok else '[취소] 거부됨 (다운로드 유지)'}"
        )

    def _demo_modal_redownload_duplicate(self) -> None:
        self._log("[M02] 작업 재다운로드 확인 모달 호출 대기...")
        ok = ask_confirm_dialog(
            parent=self,
            text="이미 추가한 작업입니다. 다시 다운로드하시겠습니까?",
        )
        self._log(
            f"[M02] 재다운로드 결과: {'[확인] 승인됨 (클린 리셋 재시작)' if ok else '[취소] 거부됨 (기존 카드 유지)'}"
        )

    def _demo_modal_clear_cookie(self) -> None:
        self._log("[M03] 쿠키 초기화 확인 모달 (Danger 빨간 강조) 호출 대기...")
        ok = ask_confirm_dialog(
            parent=self,
            text="저장된 쿠키를 삭제하시겠습니까?",
            is_danger=True,
        )
        self._log(
            f"[M03] 쿠키 초기화 결과: {'[확인] 승인됨 (쿠키 삭제 실행)' if ok else '[취소] 거부됨'}"
        )

    def _demo_modal_file_conflict(self) -> None:
        vod_sample = VodInfo(
            video_no="15021267",
            video_title="즐거운 치지직 방송 다시보기 풀영상",
            channel_name="스트리머A",
            duration=7320,
            live_open_date="2026-09-07",
        )
        fn = generate_vod_filename(vod_sample, ext=".mp4")
        self._log(f"[M04] 파일명 중복 충돌 모달 (간소화 문구, {fn}) 호출 대기...")
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Chzzk Downloader")
        msg_box.setText(f"이미 동일한 이름의 파일이 존재합니다:\n{fn}")
        overwrite_btn = msg_box.addButton("덮어쓰기", QMessageBox.ButtonRole.AcceptRole)
        rename_btn = msg_box.addButton("이름 변경", QMessageBox.ButtonRole.ActionRole)
        msg_box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(rename_btn)
        msg_box.exec()

        clicked = msg_box.clickedButton()
        if clicked == overwrite_btn:
            choice = "덮어쓰기"
        elif clicked == rename_btn:
            choice = "이름 변경 (1 추가)"
        else:
            choice = "취소"
        self._log(f"[M04] 파일 중복 선택 결과: [{choice}]")

    def _demo_modal_cookie_info(self) -> None:
        self._log("[M05/M06] 쿠키 안내 모달 호출")
        QMessageBox.information(
            self,
            "Chzzk Downloader",
            "쿠키 파일에서 2개의 쿠키를 성공적으로 불러왔습니다.",
        )
        self._log("[M05/M06] 안내 모달 닫힘")

    def _demo_modal_folder_error(self) -> None:
        self._log("[M07] 폴더 권한 오류 경고 모달 호출")
        QMessageBox.warning(
            self,
            "Chzzk Downloader",
            "선택한 폴더에 쓰기 권한이 없습니다:\nC:\\System\\Restricted\n\n다른 폴더를 선택해주세요.",
        )
        self._log("[M07] 경고 모달 닫힘")

    def _demo_modal_external_link(self) -> None:
        self._log("[M08] 외부 링크 이동 확인 모달 (치지직 뱃지 클릭) 호출 대기...")
        ok = ask_confirm_dialog(
            parent=self,
            text="해당 링크로 이동합니다.\n\n이동하시겠습니까?\nhttps://chzzk.naver.com/video/15021267",
            title="Chzzk Downloader",
        )
        self._log(
            f"[M08] 링크 이동 결과: {'[확인] 승인됨 (브라우저 이동)' if ok else '[취소] 거부됨'}"
        )

    def _demo_modal_ffmpeg_error(self) -> None:
        self._log("[M09] FFmpeg 실행 파일 오류 경고 모달 호출")
        QMessageBox.warning(
            self,
            "Chzzk Downloader",
            "선택한 파일이 유효한 FFmpeg 실행 파일이 아닙니다:\nC:\\invalid\\path\\fake_ffmpeg.exe\n\n상태: 실행 실패",
        )
        self._log("[M09] 경고 모달 닫힘")

    def _demo_modal_delete_file(self) -> None:
        vod_sample = VodInfo(
            video_no="15021267",
            video_title="즐거운 치지직 방송 다시보기 풀영상",
            channel_name="스트리머A",
            duration=7320,
            live_open_date="2026-09-07",
        )
        fn = generate_vod_filename(vod_sample, ext=".mp4")
        self._log(f"[M10] 파일 삭제 확인 모달 (Danger 빨간 강조, {fn}) 호출 대기...")
        ok = ask_confirm_dialog(
            parent=self,
            text=f"다음 파일이 삭제됩니다:\n{fn}",
            title="Chzzk Downloader",
            is_danger=True,
        )
        self._log(
            f"[M10] 파일 삭제 결과: {'[확인] 승인됨 (휴지통 안전 삭제 실행)' if ok else '[취소] 거부됨'}"
        )

    # --- 작업 목록 카드 데모 탭 구성 ---

    def _create_cards_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        info_lbl = QLabel(
            "💡 작업 카드의 상태별 레이아웃(C01~C09, VOD/Live 다운로드 및 완료 분기, 호버 툴바)을 확인하세요.",
            container,
        )
        info_lbl.setStyleSheet("color: #9ca3af; font-size: 12px; margin-bottom: 2px;")
        layout.addWidget(info_lbl)

        scroll = QScrollArea(container)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #374151; border-radius: 6px; background-color: #111827; }"
        )

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(12, 12, 12, 12)
        scroll_layout.setSpacing(14)

        # Mock VodInfo 객체들
        mock_ready_vod = VodInfo(
            video_no="15021267",
            video_title="즐거운 치지직 방송 다시보기 풀영상",
            channel_name="스트리머A",
            duration=7320,
            formats=[
                VodFormatInfo(format_id="1080p60", height=1080, fps=60.0),
                VodFormatInfo(format_id="720p", height=720, fps=30.0),
                VodFormatInfo(format_id="480p", height=480, fps=30.0),
            ],
            live_open_date="2026-09-07",
        )

        mock_downloading_vod = VodInfo(
            video_no="15033444",
            video_title="김나성박이 (8STXaDJBI1)",
            channel_name="김나성",
            duration=26,
            formats=[VodFormatInfo(format_id="1080p", height=1080, fps=60.0)],
        )

        mock_live_vod = VodInfo(
            video_no="live9999",
            video_title="퍼즐게임 인챈트 평균 넘기기",
            channel_name="따효니",
            duration=140,
            formats=[VodFormatInfo(format_id="1080p", height=1080, fps=60.0)],
            live_open_date="2026-10-03",
        )

        mock_failed_vod = VodInfo(
            video_no="15099888",
            video_title="세그먼트 전송 실패 VOD",
            channel_name="스트리머C",
            duration=1800,
            formats=[VodFormatInfo(format_id="1080p", height=1080, fps=60.0)],
        )

        # [C01] ANALYZING
        self._add_card_section(
            scroll_layout,
            "[C01] 분석 중 (ANALYZING) - 좌측 썸네일 중앙 회색 스피너, 읽는 중… 상태 (호버 시 2번: [📁] [✕])",
            TaskCardWidget(
                raw_url="https://chzzk.naver.com/video/15021267",
                status=TaskStatus.ANALYZING,
            ),
        )

        # [C02] READY
        self._add_card_section(
            scroll_layout,
            "[C02] 정상 대기 (READY) - 마우스 호버 시 2번 위치에 [📁 폴더 열기] + [✕ 목록 삭제]",
            TaskCardWidget(
                raw_url="https://chzzk.naver.com/video/15021267",
                status=TaskStatus.READY,
                vod_info=mock_ready_vod,
            ),
        )

        # [C03-VOD] DOWNLOADING (VOD)
        card_downloading_vod = TaskCardWidget(
            raw_url="https://chzzk.naver.com/video/15033444",
            status=TaskStatus.DOWNLOADING,
            vod_info=mock_downloading_vod,
            is_live=False,
        )
        card_downloading_vod.update_progress(
            TaskProgress(
                task_id="15033444",
                downloaded_bytes=534_200_000,
                total_bytes=1_250_000_000,
                percentage=42.7,
                speed_str="15.4 MB/s",
                eta_seconds=205,
                eta_str="00:03:25",
                elapsed_seconds=75.0,
            )
        )
        self._add_card_section(
            scroll_layout,
            "[C03-VOD] VOD 다운로드 중 - 4번: [Z] [■] 미니멀 진행바 + 42% / 3번: 15.4 MB/s | 00:03:25 | ⬇ 534.2 MB",
            card_downloading_vod,
        )

        # [C03-Live] DOWNLOADING (Live, 사진 1 규격)
        card_downloading_live = TaskCardWidget(
            raw_url="https://chzzk.naver.com/live/ddahyoni",
            status=TaskStatus.DOWNLOADING,
            vod_info=mock_live_vod,
            is_live=True,
        )
        card_downloading_live.update_progress(
            TaskProgress(
                task_id="live9999",
                downloaded_bytes=19_900_000,
                total_bytes=0,
                percentage=0.0,
                speed_str="1.2 MB/s",
                eta_seconds=0,
                eta_str="",
                elapsed_seconds=11.0,
            )
        )
        self._add_card_section(
            scroll_layout,
            "[C03-Live] 라이브 녹화 중 (사진 1) - 4번: [Z] [📺▶] 녹화 중… [🔄] [■] / 3번: 🕒 00:11   ⬇ 19.9 MB (속도 제외)",
            card_downloading_live,
        )

        # [C04] QUEUED (순번 대기)
        card_queued = TaskCardWidget(
            raw_url="https://chzzk.naver.com/video/15033444",
            status=TaskStatus.QUEUED,
            vod_info=mock_downloading_vod,
        )
        card_queued.set_waiting_position(2)
        self._add_card_section(
            scroll_layout,
            "[C04] 순번 대기 (QUEUED) - 대기 순번 라벨 (대기 순번: 2번), 썸네일 대기 텍스트",
            card_queued,
        )

        # [C05] FAILED_INVALID
        card_invalid = TaskCardWidget(
            raw_url="https://chzzk.naver.com/video/150700935y5",
            status=TaskStatus.FAILED_INVALID,
        )
        card_invalid.set_failed(
            TaskStatus.FAILED_INVALID,
            error_message="HTTP Error 404: Not Found (비디오를 찾을 수 없거나 비공개 영상입니다)",
        )
        self._add_card_section(
            scroll_layout,
            "[C05] 실패 - Invalid (FAILED_INVALID) - 제목 'Invalid: {url}', 빨간색 좌측 바, [치지직 뱃지] + [🗨️! 툴팁]",
            card_invalid,
        )

        # [C06] FAILED_LOGIN_REQUIRED
        card_login = TaskCardWidget(
            raw_url="https://chzzk.naver.com/video/15070093",
            status=TaskStatus.FAILED_LOGIN_REQUIRED,
        )
        card_login.set_failed(
            TaskStatus.FAILED_LOGIN_REQUIRED,
            error_message="Login required to access this 19+ video (성인 인증 및 네이버 로그인이 필요합니다)",
        )
        self._add_card_section(
            scroll_layout,
            "[C06] 실패 - 로그인 필요 (FAILED_LOGIN_REQUIRED) - 빨간색 바, 2줄 URL, [치지직] + [🗨️!] + [🍪] + [N]",
            card_login,
        )

        # [C07] FAILED_DOWNLOAD
        card_download_fail = TaskCardWidget(
            raw_url="https://chzzk.naver.com/video/15099888",
            status=TaskStatus.FAILED_DOWNLOAD,
            vod_info=mock_failed_vod,
        )
        card_download_fail.set_failed(
            TaskStatus.FAILED_DOWNLOAD,
            error_message="FFmpeg error: -extension_picky 0 argument rejected (FFmpeg 호환성 오류 또는 CDN 400 차단)",
        )
        self._add_card_section(
            scroll_layout,
            "[C07] 실패 - 다운로드 오류 (FAILED_DOWNLOAD) - 제목 'Download failed: {url}', 주황색 좌측 바, [치지직] + [🗨️! 툴팁]",
            card_download_fail,
        )

        # [C08-VOD] COMPLETED (VOD, 사진 2 상단 규격)
        card_completed_vod = TaskCardWidget(
            raw_url="https://chzzk.naver.com/video/15033444",
            status=TaskStatus.READY,
            vod_info=mock_downloading_vod,
            is_live=False,
        )
        card_completed_vod.set_completed(Path(__file__).resolve())
        self._add_card_section(
            scroll_layout,
            "[C08-VOD] VOD 완결 (완료 및 중단, 사진 2 상단) - 4번: [Z] 단독 / 3번: 🕒 00:26   ⬇ 파일크기 (호버 시 4대 액션 툴바)",
            card_completed_vod,
        )

        # [C08-Live] COMPLETED / STOPPED (Live, 사진 2 하단 규격)
        card_completed_live = TaskCardWidget(
            raw_url="https://chzzk.naver.com/live/ddahyoni",
            status=TaskStatus.READY,
            vod_info=mock_live_vod,
            is_live=True,
        )
        card_completed_live.set_completed(Path(__file__).resolve())
        self._add_card_section(
            scroll_layout,
            "[C08-Live] 라이브 녹화 완결 (완료 및 중단, 사진 2 하단) - 4번: [Z] [📺▶] 유지 / 3번: 🕒 02:20   ⬇ 파일크기 (호버 시 4대 액션 툴바)",
            card_completed_live,
        )

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        return container

    def _add_card_section(
        self,
        layout: QVBoxLayout,
        title: str,
        card: TaskCardWidget,
    ) -> None:
        sec_box = QWidget()
        sec_layout = QVBoxLayout(sec_box)
        sec_layout.setContentsMargins(0, 0, 0, 0)
        sec_layout.setSpacing(4)

        title_lbl = QLabel(title, sec_box)
        title_lbl.setStyleSheet("color: #60a5fa; font-size: 11px; font-weight: bold;")
        sec_layout.addWidget(title_lbl)

        card.request_open_cookies.connect(
            lambda: self._log(f"작업 카드: [🍪 쿠키 설정] 클릭됨 ({card.raw_url})")
        )
        card.request_naver_login.connect(
            lambda: self._log(f"작업 카드: [N 네이버 로그인] 클릭됨 ({card.raw_url})")
        )
        card.delete_requested.connect(
            lambda: self._log(f"작업 카드: [✕ 삭제] 클릭됨 ({card.raw_url})")
        )
        card.download_started.connect(
            lambda: self._log(f"작업 카드: [▶ 다운로드 시작] 클릭됨 ({card.raw_url})")
        )
        card.download_stopped.connect(
            lambda: self._log(f"작업 카드: [■ 다운로드 중지] 클릭됨 ({card.raw_url})")
        )

        if hasattr(card, "action_delete_file_btn"):
            card.action_delete_file_btn.clicked.connect(
                lambda: self._log(f"작업 카드: [🗑️ 파일 삭제] 클릭됨 ({card.raw_url})")
            )
        if hasattr(card, "open_folder_btn"):
            card.open_folder_btn.clicked.connect(
                lambda: self._log(f"작업 카드: [📁 폴더 열기] 클릭됨 ({card.raw_url})")
            )
        if hasattr(card, "play_btn"):
            card.play_btn.clicked.connect(
                lambda: self._log(f"작업 카드: [▶ 미디어 재생] 클릭됨 ({card.raw_url})")
            )

        sec_layout.addWidget(card)
        layout.addWidget(sec_box)


def main() -> None:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    window = FeedbackShowcaseWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
