"""UI 피드백(확인 모달 M01~M10, 토스트 T01~T07, 쇼케이스 창, 진단창 및 치지직 뱃지) GUI 테스트."""

from __future__ import annotations

import sys

import pytest
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMessageBox

import chzzk_downloader.gui.feedback_showcase
import chzzk_downloader.gui.task_card
from chzzk_downloader.gui.dialogs import create_confirm_box
from chzzk_downloader.gui.feedback_showcase import FeedbackShowcaseWindow
from chzzk_downloader.gui.task_card import TaskCardWidget, TaskStatus
from chzzk_downloader.gui.toast import ToastType, ToastWidget


@pytest.mark.ticket("T0109")
def test_confirm_modal_buttons_and_highlight(qtbot) -> None:
    """[T0109] 모달에서 Yes/No 대신 '확인'/'취소' 버튼을 사용하고 '확인'에 기본 하이라이트가 적용되는지 검증."""
    msg_box, confirm_btn, cancel_btn = create_confirm_box(
        parent=None,
        title="테스트 제목",
        text="테스트 내용",
    )
    qtbot.addWidget(msg_box)

    # 1. 버튼 텍스트 확인
    assert confirm_btn.text() == "확인"
    assert cancel_btn.text() == "취소"

    # 2. 확인 버튼에 defaultButton 설정 및 하이라이트 스타일 확인
    assert msg_box.defaultButton() == confirm_btn
    assert "#2563eb" in confirm_btn.styleSheet()
    assert "font-weight: bold" in confirm_btn.styleSheet()

    # 3. danger 옵션(예: 쿠키 초기화) 시 빨간색 하이라이트 확인
    danger_box, danger_confirm, _ = create_confirm_box(
        parent=None,
        title="위험 삭제",
        text="정말 삭제하시겠습니까?",
        is_danger=True,
    )
    qtbot.addWidget(danger_box)
    assert danger_box.defaultButton() == danger_confirm
    assert "#ef4444" in danger_confirm.styleSheet()


def test_confirm_modals_use_korean_confirm_cancel_and_default_highlight(qtbot) -> None:
    """모든 질문형 모달이 Yes/No 없이 '확인'/'취소'를 사용하고 '확인'에 기본 하이라이트가 적용되는지 검증."""
    for modal_id, text, is_danger in [
        ("M01", "정말 중지하시겠습니까?", False),
        ("M02", "이미 추가한 작업입니다. 다시 다운로드하시겠습니까?", False),
        ("M03", "저장된 쿠키를 삭제하시겠습니까?", True),
    ]:
        msg_box, confirm_btn, cancel_btn = create_confirm_box(
            parent=None,
            text=text,
            is_danger=is_danger,
        )
        qtbot.addWidget(msg_box)

        # 0. 윈도우 아웃 프레임(타이틀) Chzzk Downloader 통일 검증
        if sys.platform != "darwin":
            assert msg_box.windowTitle() == "Chzzk Downloader", (
                f"[{modal_id}] 창 타이틀 불일치"
            )
        else:
            assert msg_box.windowTitle() in ("", "Chzzk Downloader"), (
                f"[{modal_id}] macOS 창 타이틀 예외 불일치"
            )

        # 1. 한글 확인/취소 검증
        assert confirm_btn.text() == "확인", f"[{modal_id}] 확인 버튼 텍스트 불일치"
        assert cancel_btn.text() == "취소", f"[{modal_id}] 취소 버튼 텍스트 불일치"

        # 2. '확인' 버튼에 기본 포커스(defaultButton) 설정 검증
        assert msg_box.defaultButton() == confirm_btn, (
            f"[{modal_id}] 기본 버튼이 확인이 아님"
        )

        # 3. 스타일시트 하이라이트 검증
        style = confirm_btn.styleSheet()
        assert "font-weight: bold" in style, f"[{modal_id}] 확인 버튼 굵게 표시 누락"
        if is_danger:
            assert "#ef4444" in style, (
                f"[{modal_id}] 위험 확인 버튼 빨간색 하이라이트 누락"
            )
        else:
            assert "#2563eb" in style, (
                f"[{modal_id}] 일반 확인 버튼 파란색 하이라이트 누락"
            )

        # 4. 문체 검증 (~하시겠습니까?)
        assert text.strip().endswith("하시겠습니까?"), (
            f"[{modal_id}] 질문형 문체 규격 불일치"
        )


def test_toast_catalog_types_and_appearance(qtbot) -> None:
    """토스트 카탈로그에 정의된 각 토스트 유형이 정상 생성되고 텍스트를 노출하는지 검증."""
    container = FeedbackShowcaseWindow()
    qtbot.addWidget(container)
    toast: ToastWidget = container.toast

    # T01: URL 추가 토스트
    msg = (
        '<span style="color: #3b82f6; font-weight: bold; font-size: 14px;">+</span> '
        '<span style="color: #ffffff;">https://chzzk.naver.com/video/15016450</span>'
    )
    toast.show_toast(msg, ToastType.SUCCESS, auto_dismiss_ms=2000)
    assert toast.isHidden() is False
    assert "https://chzzk.naver.com/video/15016450" in toast.label.text()

    # T02: 쿠키 재분석 안내 토스트 (SUCCESS)
    toast.show_toast(
        "쿠키가 등록되어 로그인 필요 작업을 다시 분석합니다.", ToastType.SUCCESS
    )
    assert toast.isHidden() is False
    assert "쿠키가 등록되어 로그인 필요 작업을 다시 분석합니다." in toast.label.text()

    # T03: 진행중 중복 거부 토스트 (WARNING, ⚠️ 아이콘)
    toast.show_toast(
        '<span style="color: #f59e0b;">⚠️</span> 이미 추가한 작업입니다.',
        ToastType.WARNING,
    )
    assert toast.isHidden() is False
    assert "이미 추가한 작업입니다." in toast.label.text()
    assert "⚠️" in toast.label.text()

    # T06: 만료 경고 액션 토스트 (쿠키를 갱신하세요, 🍪/N 아이콘 버튼 및 툴팁)
    toast.show_action_toast(
        "쿠키를 갱신하세요",
        buttons=[
            ("🍪", "#3b82f6", lambda: None, "쿠키 설정"),
            ("N", "#03c75a", lambda: None, "네이버 로그인"),
        ],
    )
    assert toast.isHidden() is False
    assert "쿠키를 갱신하세요" in toast.label.text()
    assert len(toast._action_buttons) == 2
    assert toast._action_buttons[0].text() == "🍪"
    assert toast._action_buttons[0].toolTip() == "쿠키 설정"
    assert toast._action_buttons[1].text() == "N"
    assert toast._action_buttons[1].toolTip() == "네이버 로그인"

    # T07: FFmpeg 미가용 경고 토스트 (WARNING, ⚠️ 아이콘)
    toast.show_toast(
        '<span style="color: #f59e0b;">⚠️</span> FFmpeg를 사용할 수 없습니다. 환경설정에서 FFmpeg를 설정해주세요.',
        ToastType.WARNING,
    )
    assert toast.isHidden() is False
    assert "FFmpeg를 사용할 수 없습니다" in toast.label.text()
    assert "⚠️" in toast.label.text()


def test_feedback_showcase_window_initialization(qtbot) -> None:
    """피드백 쇼케이스 창이 오류 없이 열리고 모든 데모 버튼이 탑재되어 있는지 검증."""
    window = FeedbackShowcaseWindow()
    qtbot.addWidget(window)
    window.show()

    # 창 타이틀 검증
    assert "UI 피드백 쇼케이스" in window.windowTitle()

    # 로그 영역 초기화 검증
    assert "쇼케이스가 준비되었습니다" in window.log_edit.toPlainText()

    # 토스트 데모 슬롯 호출 시 로그 기록 검증
    window._demo_toast_add_url()
    assert "[T01] URL 추가 토스트 호출" in window.log_edit.toPlainText()

    window._demo_toast_reanalyze_success()
    assert (
        "[T02] 쿠키 재분석 토스트는 백그라운드 자동 재분석으로 전환"
        in window.log_edit.toPlainText()
    )


def test_feedback_showcase_modals_use_unified_title(qtbot, monkeypatch) -> None:
    """피드백 쇼케이스 창의 모든 모달 호출 시 'Chzzk Downloader' 타이틀이 사용되는지 검증."""
    window = FeedbackShowcaseWindow()
    qtbot.addWidget(window)

    captured_titles: list[str] = []

    # 1) ask_confirm_dialog 검증 (M01, M02, M03)
    def mock_ask(parent=None, text="", title="Chzzk Downloader", **kwargs):
        captured_titles.append(title)
        return True

    monkeypatch.setattr(
        chzzk_downloader.gui.feedback_showcase, "ask_confirm_dialog", mock_ask
    )

    window._demo_modal_stop_download()
    window._demo_modal_redownload_duplicate()
    window._demo_modal_clear_cookie()

    # 2) QMessageBox.information / warning 검증 (M05, M07)
    def mock_info(parent, title, text, *args, **kwargs):
        captured_titles.append(title)

    def mock_warning(parent, title, text, *args, **kwargs):
        captured_titles.append(title)

    monkeypatch.setattr(QMessageBox, "information", mock_info)
    monkeypatch.setattr(QMessageBox, "warning", mock_warning)

    window._demo_modal_cookie_info()
    window._demo_modal_folder_error()
    window._demo_modal_ffmpeg_error()

    # 3) M04 파일 충돌 모달 검증
    def mock_exec(self):
        captured_titles.append(self.windowTitle())
        return 0

    monkeypatch.setattr(QMessageBox, "exec", mock_exec)
    window._demo_modal_file_conflict()

    assert len(captured_titles) == 7
    for title in captured_titles:
        if sys.platform != "darwin":
            assert title == "Chzzk Downloader", f"쇼케이스 모달 타이틀 불일치: {title}"
        else:
            assert title in ("", "Chzzk Downloader"), (
                f"macOS 쇼케이스 모달 타이틀 예외 불일치: {title}"
            )


def test_m04_compact_text_and_task_card_auth_buttons_iconized(qtbot) -> None:
    """M04 모달 문구 및 작업 카드의 뱃지/에러툴팁/인증버튼/좌측컬러바 검증."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/12345",
        status=TaskStatus.FAILED_LOGIN_REQUIRED,
    )
    qtbot.addWidget(card)

    # 1. 2줄 텍스트 및 빨간색 좌측 5px 바 검증
    assert "Login required; Please login\n" in card.title_label.text()
    assert "border-left: 5px solid #ef4444" in card.styleSheet()
    assert card.status_label.isHidden() is True
    assert card.status_label.text() == ""

    # 2. 치지직 뱃지 (툴팁 없음, 클릭 가능)
    assert card.chzzk_badge.text() == "Z"
    assert card.chzzk_badge.toolTip() == ""
    assert card.chzzk_badge.width() == 24
    assert card.chzzk_badge.height() == 22

    # 3. 말풍선 에러 버튼 (툴팁 "작업 정보")
    assert card.error_info_btn.text() == "🗨️!"
    assert card.error_info_btn.toolTip() == "작업 정보"
    assert card.error_info_btn.width() == 24
    assert card.error_info_btn.height() == 22

    # 4. 인증 버튼 아이콘화 및 툴팁 검증
    assert card.cookie_btn.text() == "🍪"
    assert card.cookie_btn.toolTip() == "쿠키 설정"
    assert card.cookie_btn.width() == 24
    assert card.cookie_btn.height() == 22

    assert card.login_btn.text() == "N"
    assert card.login_btn.toolTip() == "네이버 로그인"
    assert card.login_btn.width() == 24
    assert card.login_btn.height() == 22


def test_toast_unified_dark_background_and_dynamic_pill_sizing(qtbot) -> None:
    """모든 토스트가 검은 배경을 사용하고, 고정 최소너비 없이 내용 맞춤형 컴팩트 알약 크기를 유지하는지 검증."""
    container = FeedbackShowcaseWindow()
    qtbot.addWidget(container)
    toast: ToastWidget = container.toast

    # T01 URL 토스트
    msg = (
        '<span style="color: #3b82f6; font-weight: bold; font-size: 14px;">+</span> '
        '<span style="color: #ffffff;">https://chzzk.naver.com/video/15016450</span>'
    )
    toast.show_toast(msg, ToastType.SUCCESS, auto_dismiss_ms=2000)
    style = toast.styleSheet()
    assert "rgba(20, 20, 20, 230)" in style
    assert toast.close_btn.isHidden() is True

    # T03 경고 토스트
    toast.show_toast("⚠️ 이미 추가한 작업입니다.", ToastType.WARNING)
    style_warning = toast.styleSheet()
    assert "rgba(20, 20, 20, 230)" in style_warning
    assert toast.width() < 400

    # T06 액션 토스트
    toast.show_action_toast(
        "쿠키를 갱신하세요",
        buttons=[
            ("🍪", "transparent", lambda: None, "쿠키 설정"),
            ("N", "#03c75a", lambda: None, "네이버 로그인"),
        ],
    )
    assert toast.close_btn.isHidden() is False
    assert len(toast._action_buttons) == 2
    cookie_btn = toast._action_buttons[0]
    assert "background-color: transparent" in cookie_btn.styleSheet()


def test_feedback_showcase_task_card_gallery_tab(qtbot) -> None:
    """피드백 쇼케이스 창에 작업 카드 갤러리 탭이 구성되어 있고 7대 카드가 렌더링되는지 검증."""
    window = FeedbackShowcaseWindow()
    qtbot.addWidget(window)

    assert window.tabs.count() == 2
    assert "토스트" in window.tabs.tabText(0)
    assert "작업 목록 카드" in window.tabs.tabText(1)


def test_task_info_window_modeless_and_diagnostic_format(qtbot) -> None:
    """말풍선 에러 버튼 클릭 시 비모달 진단 팝업 창이 뜨고 사용자 요청 포맷대로 텍스트가 채워지는지 검증."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15070093",
        status=TaskStatus.FAILED_LOGIN_REQUIRED,
    )
    qtbot.addWidget(card)
    card.set_failed(
        TaskStatus.FAILED_LOGIN_REQUIRED, "Login required to access this 19+ video"
    )

    # 팝업 열기
    card.open_task_info_window()
    assert hasattr(card, "_info_win")
    assert card._info_win is not None
    info_win = card._info_win
    qtbot.addWidget(info_win)

    # 1. 비모달 및 가시성 검증
    assert info_win.isVisible() is True
    assert info_win.isModal() is False

    # 2. 내용 포맷 검증
    content = info_win.text_edit.toPlainText()
    assert "Login required; Please login" in content
    assert "https://chzzk.naver.com/video/15070093" in content
    assert "platform / locale:" in content
    assert "order / group / uid:" in content
    assert "[Messages]" in content
    assert "LoginRequired_chzzk" in content

    # 3. 클립보드 복사 버튼 검증
    info_win._copy_to_clipboard()
    assert "복사됨" in info_win.copy_btn.text()
    info_win.close()


def test_task_card_chzzk_badge_confirm_modal_and_browser(qtbot, monkeypatch) -> None:
    """치지직 뱃지 클릭 시 확인/취소 모달 승인 후 브라우저 URL 오픈 검증."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15070093",
        status=TaskStatus.FAILED_INVALID,
    )
    qtbot.addWidget(card)

    opened_urls: list[str] = []

    # 1) 확인 모달 승인 모킹
    def mock_ask(*args, **kwargs):
        return True

    # 2) QDesktopServices.openUrl 모킹
    def mock_open_url(url):
        opened_urls.append(url.toString())
        return True

    monkeypatch.setattr(chzzk_downloader.gui.task_card, "ask_confirm_dialog", mock_ask)
    monkeypatch.setattr(QDesktopServices, "openUrl", mock_open_url)

    # 뱃지 클릭
    card.chzzk_badge.click()

    assert len(opened_urls) == 1
    assert opened_urls[0] == "https://chzzk.naver.com/video/15070093"
