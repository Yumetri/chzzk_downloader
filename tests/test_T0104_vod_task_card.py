"""T0104. VOD 분석 결과 카드, 작업 목록 즉시 등록 및 라이브 시작일 기재 단위/통합 테스트."""

from unittest.mock import patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QListWidgetItem

from chzzk_downloader.config import SUCCESS_TOAST_DURATION_MS
from chzzk_downloader.core.ytdlp import (
    VodFormatInfo,
    VodInfo,
    VodNotFoundError,
    YtDlpError,
)
from chzzk_downloader.gui.main_window import MainWindow, TaskListWidget
from chzzk_downloader.gui.task_card import (
    TaskCardWidget,
    TaskStatus,
    format_duration,
)


@pytest.fixture
def main_window(qtbot):
    """메인 창 인스턴스를 생성하고 표시하는 fixture."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    return window


def test_vod_info_display_name_with_live_date():
    """라이브 시작일(live_open_date)이 존재할 때 '[스트리머] YYYY-MM-DD 제목' 규칙 검증."""
    info = VodInfo(
        video_no="15016450",
        video_title="치지직 테스트 방송 다시보기",
        channel_name="스트리머A",
        live_open_date="2024-05-06",
    )
    expected = "[스트리머A] 2024-05-06 치지직 테스트 방송 다시보기"
    assert info.display_name == expected


def test_vod_info_display_name_without_live_date():
    """라이브 시작일이 없을 때 '[스트리머] 제목' 규칙 검증."""
    info = VodInfo(
        video_no="99999",
        video_title="일반 업로드 영상",
        channel_name="스트리머B",
        live_open_date="",
    )
    expected = "[스트리머B] 일반 업로드 영상"
    assert info.display_name == expected


def test_format_duration_helper():
    """초 단위 재생 시간 포맷 변환 검증."""
    assert format_duration(0) == "00:00"
    assert format_duration(-10) == "00:00"
    assert format_duration(65) == "01:05"
    assert format_duration(3665) == "01:01:05"


def test_task_card_analyzing_state_and_hover_action(qtbot):
    """분석 진행 상태(ANALYZING)의 카드 레이아웃, 줄바꿈, 호버 시 액션 아이콘 표시 검증."""
    url = "https://chzzk.naver.com/video/15016450"
    card = TaskCardWidget(raw_url=url, status=TaskStatus.ANALYZING)
    qtbot.addWidget(card)

    assert card.status == TaskStatus.ANALYZING
    assert card.title_label.text() in (f"읽는 중… {url}", f"분석 중... ({url})")
    assert card.title_label.wordWrap() is True
    assert card.status_label.text() == "분석 중..."
    assert card.thumb_label.text() == "분석 중"
    assert card.auth_container.isHidden() is True
    assert "#ef4444" not in card.styleSheet()

    # 액션 아이콘(삭제 버튼)은 평소에 숨겨져 있음 (공간은 retainSizeWhenHidden으로 유지)
    assert card.delete_btn.isHidden() is True
    assert card.delete_btn.sizePolicy().retainSizeWhenHidden() is True

    # 마우스 진입(enterEvent) 시 노출
    card.enterEvent(None)
    assert card.delete_btn.isHidden() is False

    # 마우스 이탈(leaveEvent) 시 다시 숨김
    card.leaveEvent(None)
    assert card.delete_btn.isHidden() is True


def test_task_card_ready_state_and_update(qtbot):
    """분석 완료(READY) 상태 갱신 시 메타데이터 및 화질/시간 표시 검증."""
    url = "https://chzzk.naver.com/video/15016450"
    card = TaskCardWidget(raw_url=url, status=TaskStatus.ANALYZING)
    qtbot.addWidget(card)

    mock_info = VodInfo(
        video_no="15016450",
        video_title="마인크래프트 야생",
        channel_name="스트리머C",
        duration=7325,  # 02:02:05
        formats=[
            VodFormatInfo(format_id="720p", height=720, fps=30.0),
            VodFormatInfo(format_id="1080p", height=1080, fps=60.0),
        ],
        live_open_date="2024-05-06",
    )

    card.update_with_vod_info(mock_info)

    assert card.status == TaskStatus.READY
    assert card.title_label.text() == "[스트리머C] 2024-05-06 마인크래프트 야생"
    assert card.status_label.text() == "1080p60 | 02:02:05"
    assert card.thumb_label.text() == "VOD"
    assert card.auth_container.isHidden() is True
    assert "#ef4444" not in card.styleSheet()


def test_task_card_thumbnail_loading(qtbot):
    """썸네일 바이트 로드 시 QLabel에 QPixmap이 반영되는지 검증."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/1", status=TaskStatus.READY
    )
    qtbot.addWidget(card)

    # 10x10 dummy image bytes
    image = QImage(10, 10, QImage.Format.Format_RGB32)
    image.fill(QColor("blue"))
    from PyQt6.QtCore import QBuffer, QIODevice

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    img_bytes = bytes(buf.data().data())

    card._on_thumbnail_loaded(img_bytes)
    assert card.thumb_label.pixmap() is not None
    assert card.thumb_label.text() == ""


def test_task_card_failed_invalid_styling(qtbot):
    """유효하지 않은 URL 또는 분석 실패(FAILED_INVALID) 시 빨간색 하이라이트 검증."""
    url = "https://invalid-url.com/abc"
    card = TaskCardWidget(raw_url=url, status=TaskStatus.FAILED_INVALID)
    qtbot.addWidget(card)

    assert card.status == TaskStatus.FAILED_INVALID
    assert card.title_label.text() == f"Invalid: {url}"
    assert card.thumb_label.text() == "✕"
    assert card.auth_container.isHidden() is True

    # 빨간색 시각적 하이라이트 검증
    assert "#ef4444" in card.styleSheet()
    assert "#ef4444" in card.title_label.styleSheet()


def test_task_card_failed_login_required_styling(qtbot):
    """로그인 필요(FAILED_LOGIN_REQUIRED) 시 빨간색 하이라이트 및 인증 영역 노출 검증."""
    url = "https://chzzk.naver.com/video/191919"
    card = TaskCardWidget(raw_url=url, status=TaskStatus.FAILED_LOGIN_REQUIRED)
    qtbot.addWidget(card)

    assert card.status == TaskStatus.FAILED_LOGIN_REQUIRED
    assert card.title_label.text() == f"Login required; Please login: {url}"
    assert card.status_label.text() == "로그인 필요"
    assert card.thumb_label.text() == "인증 필요"
    assert card.auth_container.isHidden() is False

    # 빨간색 시각적 하이라이트 검증
    assert "#ef4444" in card.styleSheet()
    assert "#ef4444" in card.title_label.styleSheet()


def test_task_card_delete_requested_signal(qtbot):
    """카드 내 삭제(✕) 버튼 클릭 시 delete_requested 시그널 방출 검증."""
    card = TaskCardWidget("https://chzzk.naver.com/video/123", TaskStatus.READY)
    qtbot.addWidget(card)
    with qtbot.waitSignal(card.delete_requested, timeout=1000):
        qtbot.mouseClick(card.delete_btn, Qt.MouseButton.LeftButton)


def test_task_list_add_at_top_and_delete(qtbot):
    """새 작업 카드가 목록 최상단(Index 0)에 추가되어 오래된 항목이 아래로 가는지 검증."""
    task_list = TaskListWidget()
    qtbot.addWidget(task_list)
    assert task_list.stack.currentWidget() == task_list.empty_label
    assert task_list.list_widget.count() == 0

    # 1. 첫 번째 카드 추가 (오래된 카드)
    card1 = TaskCardWidget("https://chzzk.naver.com/video/1", TaskStatus.ANALYZING)
    item1 = task_list.add_task_card(card1)
    assert isinstance(item1, QListWidgetItem)
    assert task_list.list_widget.count() == 1
    assert task_list.list_widget.itemWidget(task_list.list_widget.item(0)) == card1

    # 2. 두 번째 카드 추가 (새 카드) -> Index 0 최상단에 위치해야 함
    card2 = TaskCardWidget("https://chzzk.naver.com/video/2", TaskStatus.ANALYZING)
    task_list.add_task_card(card2)
    assert task_list.list_widget.count() == 2
    assert task_list.list_widget.itemWidget(task_list.list_widget.item(0)) == card2
    assert task_list.list_widget.itemWidget(task_list.list_widget.item(1)) == card1

    # 3. card2 삭제 시 card1만 남음
    card2.delete_btn.click()
    assert task_list.list_widget.count() == 1
    assert task_list.list_widget.itemWidget(task_list.list_widget.item(0)) == card1

    # 4. card1 삭제 시 빈 상태 복귀
    card1.delete_btn.click()
    assert task_list.list_widget.count() == 0
    assert task_list.stack.currentWidget() == task_list.empty_label


def test_main_window_invalid_url_immediately_adds_failed_card_and_toast(
    main_window, qtbot
):
    """잘못된 URL 입력 시 작업 목록 최상단에 빨간색 카드가 즉시 추가되고 토스트가 뜨는지 검증."""
    invalid_url = "https://not-chzzk.com/test"
    main_window.url_input.setText(invalid_url)
    qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

    # 1. 입력칸 즉시 클리어 검증
    assert main_window.url_input.text() == ""

    # 2. 작업 목록 최상단에 빨간색 실패 카드 즉시 등록 검증
    assert main_window.task_list.count() == 1
    card = main_window.task_list.itemWidget(main_window.task_list.item(0))
    assert isinstance(card, TaskCardWidget)
    assert card.status == TaskStatus.FAILED_INVALID
    assert card.title_label.text() == f"Invalid: {invalid_url}"
    assert "#ef4444" in card.styleSheet()

    # 3. 토스트 알림 검증: Invalid: {URL}, 2초 자동 소멸 타이머 동작
    assert main_window.toast.isHidden() is False
    assert f"Invalid: {invalid_url}" in main_window.toast.label.text()
    assert main_window.toast._timer.isActive() is True
    assert main_window.toast._timer.interval() == SUCCESS_TOAST_DURATION_MS


def test_main_window_valid_url_success_flow(main_window, qtbot):
    """정상 치지직 VOD URL 입력 시 분석 중 카드 등록 후 라이브 시작일 포함 메타데이터로 갱신 검증."""
    mock_vod = VodInfo(
        video_no="15016450",
        video_title="테스트 라이브 방송",
        channel_name="스트리머D",
        duration=3600,
        formats=[VodFormatInfo(format_id="1080p", height=1080, fps=60.0)],
        live_open_date="2024-05-06",
    )

    test_url = "https://chzzk.naver.com/video/15016450"
    with patch("chzzk_downloader.gui.workers.extract_vod_info", return_value=mock_vod):
        main_window.url_input.setText(test_url)
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

        # 1. 카드 즉시 등록 확인 (ANALYZING)
        assert main_window.task_list.count() == 1
        card = main_window.task_list.itemWidget(main_window.task_list.item(0))
        assert isinstance(card, TaskCardWidget)

        # 2. 토스트 확인: + [URL]
        assert main_window.toast.isHidden() is False
        assert "+" in main_window.toast.label.text()
        assert test_url in main_window.toast.label.text()

        # 3. 워커 완료 대기
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

        # 4. 카드 갱신 결과 검증 (READY 또는 자동 다운로드 진입 DOWNLOADING)
        assert card.status in (TaskStatus.READY, TaskStatus.DOWNLOADING)
        assert card.title_label.text() == "[스트리머D] 2024-05-06 테스트 라이브 방송"
        assert card.status_label.text() == "1080p60 | 01:00:00"
        assert "#ef4444" not in card.styleSheet()


def test_main_window_valid_url_login_required_flow(main_window, qtbot):
    """성인인증/로그인 필요 오류 발생 시 카드가 빨간색으로 하이라이트되고 안내 문구가 반영되는지 검증."""
    test_url = "https://chzzk.naver.com/video/19000000"
    login_err = YtDlpError("Login required to access this 19+ video")

    with patch("chzzk_downloader.gui.workers.extract_vod_info", side_effect=login_err):
        main_window.url_input.setText(test_url)
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

        # 워커 완료 대기
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

        # 1. 카드 상태 및 문구 검증
        assert main_window.task_list.count() == 1
        card = main_window.task_list.itemWidget(main_window.task_list.item(0))
        assert isinstance(card, TaskCardWidget)
        assert card.status == TaskStatus.FAILED_LOGIN_REQUIRED
        expected_msg = f"Login required; Please login: {test_url}"
        assert card.title_label.text() == expected_msg
        assert "#ef4444" in card.styleSheet()
        assert card.auth_container.isHidden() is False

        # 2. 토스트 알림 동일 문구 및 2초 자동 소멸 타이머 검증
        assert main_window.toast.isHidden() is False
        assert f"Login required; Please login\n{test_url}" in main_window.toast.label.text()
        assert main_window.toast._timer.isActive() is True


def test_main_window_401_unauthorized_triggers_login_required(main_window, qtbot):
    """실제 치지직 쿠키 필요 VOD의 401 Unauthorized 오류 시 Login required 상태로 전환되는지 검증."""
    test_url = "https://chzzk.naver.com/video/15021267"
    err_401 = YtDlpError(
        "ERROR: [chzzk:video] 15021267: Failed to download MPD manifest: HTTP Error 401: Unauthorized"
    )

    with patch("chzzk_downloader.gui.workers.extract_vod_info", side_effect=err_401):
        main_window.url_input.setText(test_url)
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

        card = main_window.task_list.itemWidget(main_window.task_list.item(0))
        assert isinstance(card, TaskCardWidget)
        assert card.status == TaskStatus.FAILED_LOGIN_REQUIRED
        assert f"Login required; Please login: {test_url}" in card.title_label.text()
        assert (
            f"Login required; Please login\n{test_url}"
            in main_window.toast.label.text()
        )


def test_main_window_valid_url_not_found_flow(main_window, qtbot):
    """VOD 404 미존재 오류 발생 시 카드가 빨간색 실패로 갱신되고 Invalid: {URL} 토스트가 뜨는지 검증."""
    test_url = "https://chzzk.naver.com/video/99999999"
    not_found_err = VodNotFoundError("동영상 정보가 존재하지 않습니다.")

    with patch(
        "chzzk_downloader.gui.workers.extract_vod_info", side_effect=not_found_err
    ):
        main_window.url_input.setText(test_url)
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

        # 워커 완료 대기
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

        # 1. 카드 상태 및 문구 검증
        assert main_window.task_list.count() == 1
        card = main_window.task_list.itemWidget(main_window.task_list.item(0))
        assert isinstance(card, TaskCardWidget)
        assert card.status == TaskStatus.FAILED_INVALID
        assert card.title_label.text() == f"Invalid: {test_url}"
        assert "#ef4444" in card.styleSheet()

        # 2. 토스트 알림 검증
        assert main_window.toast.isHidden() is False
        assert f"Invalid: {test_url}" in main_window.toast.label.text()
        assert main_window.toast._timer.isActive() is True
