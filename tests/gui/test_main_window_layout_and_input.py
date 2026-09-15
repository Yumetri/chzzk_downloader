"""메인 윈도우 기본 레이아웃, URL 입력칸 제어, 클립보드 및 컨텍스트 메뉴 GUI 테스트."""

from unittest.mock import patch

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QPushButton

from chzzk_downloader.core.ytdlp import VodInfo
from chzzk_downloader.gui.main_window import MainWindow


@pytest.fixture
def main_window(qtbot):
    """메인 창 인스턴스를 생성하고 qtbot에 등록하는 fixture."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    return window


@pytest.mark.ticket("T0101")
def test_main_window_initialization(qtbot) -> None:
    """[T0101] 메인 창이 에러 없이 생성되고 기본 타이틀을 가지는지 검증."""
    win = MainWindow()
    qtbot.addWidget(win)
    assert win.windowTitle() == "치지직 VOD 다운로더"
    assert win.isVisible() is False


@pytest.mark.ticket("T0101")
def test_settings_button(main_window, qtbot) -> None:
    """[T0101] 상단 설정 버튼이 존재하고 클릭 가능한지 검증."""
    assert hasattr(main_window, "settings_btn")
    assert main_window.settings_btn.text() == "설정"
    assert main_window.settings_btn.isEnabled()

    qtbot.mouseClick(main_window.settings_btn, Qt.MouseButton.LeftButton)


@pytest.mark.ticket("T0101")
def test_input_area_layout_order(main_window) -> None:
    """[T0101] 입력 영역 배치 순서가 [붙여넣기] [URL 입력칸] [다운로드] 순인지 검증."""
    assert hasattr(main_window, "paste_btn")
    assert hasattr(main_window, "url_input")
    assert hasattr(main_window, "download_btn")

    central = main_window.centralWidget()
    assert central is not None
    central_layout = central.layout()
    assert central_layout is not None
    item1 = central_layout.itemAt(1)
    assert item1 is not None
    input_layout = item1.layout()
    assert isinstance(input_layout, QHBoxLayout)

    item0 = input_layout.itemAt(0)
    item1 = input_layout.itemAt(1)
    item2 = input_layout.itemAt(2)
    assert item0 is not None and item0.widget() == main_window.paste_btn
    assert item1 is not None and item1.widget() == main_window.url_input
    assert item2 is not None and item2.widget() == main_window.download_btn


@pytest.mark.ticket("T0101")
def test_paste_button_behavior(main_window, qtbot) -> None:
    """[T0101] 붙여넣기 버튼 속성 및 클립보드 텍스트 반영 동작 검증."""
    assert main_window.paste_btn.text() == "📋"
    assert main_window.paste_btn.toolTip() == "붙여넣기"
    assert main_window.paste_btn.isEnabled()

    clipboard = QApplication.clipboard()
    assert clipboard is not None
    test_text = "https://chzzk.naver.com/video/987654"
    clipboard.setText(test_text)

    qtbot.mouseClick(main_window.paste_btn, Qt.MouseButton.LeftButton)
    assert main_window.url_input.text() == test_text


@pytest.mark.ticket("T0101")
def test_url_input_placeholder_clear_button_and_typing(main_window, qtbot) -> None:
    """[T0101] URL 입력칸의 플레이스홀더, 삭제(Clear) 아이콘 활성화, 텍스트 입력 검증."""
    assert hasattr(main_window, "url_input")
    assert main_window.url_input.placeholderText() == "치지직 VOD URL을 입력하세요"
    assert main_window.url_input.isEnabled()
    assert main_window.url_input.isClearButtonEnabled() is True

    test_url = "https://chzzk.naver.com/video/12345"
    qtbot.keyClicks(main_window.url_input, test_url)
    assert main_window.url_input.text() == test_url

    main_window.url_input.clear()
    assert main_window.url_input.text() == ""


@pytest.mark.ticket("T0101")
def test_download_button(main_window, qtbot) -> None:
    """[T0101] 다운로드 버튼이 존재하고 클릭 가능한지 검증."""
    assert hasattr(main_window, "download_btn")
    assert main_window.download_btn.text() == "다운로드"
    assert main_window.download_btn.isEnabled()

    qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)


@pytest.mark.ticket("T0101")
def test_task_list_empty_state(main_window) -> None:
    """[T0101] 작업 목록 영역이 초기 상태에서 '작업 없음'을 표시하는지 검증."""
    assert hasattr(main_window, "task_list_widget")
    assert hasattr(main_window, "empty_label")
    assert main_window.empty_label.text() == "작업 없음"
    assert main_window.task_list_widget.stack.currentWidget() == main_window.empty_label


@pytest.mark.ticket("T0101")
def test_no_unimplemented_widgets(main_window) -> None:
    """[T0101] 아직 구현하지 않은 채널·알림·시스템 영역이 미리 생성되지 않았는지 검증."""
    all_buttons = main_window.findChildren(QPushButton)
    button_texts = [btn.text() for btn in all_buttons]

    assert set(button_texts) == {"설정", "다운로드", "📋"}
    assert not hasattr(main_window, "channel_list")
    assert not hasattr(main_window, "notification_area")
    assert not hasattr(main_window, "system_status")


@pytest.mark.ticket("T0102")
def test_empty_url_does_not_show_toast(main_window, qtbot) -> None:
    """[T0102] URL 입력칸이 비어있거나 공백만 있을 때는 토스트를 띄우지 않고 무시하는지 검증."""
    main_window.url_input.setText("")
    qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)
    assert main_window.toast.isHidden() is True

    main_window.url_input.setText("   \t\n  ")
    qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)
    assert main_window.toast.isHidden() is True

    main_window.url_input.setText("")
    qtbot.keyClick(main_window.url_input, Qt.Key.Key_Return)
    assert main_window.toast.isHidden() is True


@pytest.mark.ticket("T0102")
def test_invalid_url_shows_error_toast_and_clears_input(main_window, qtbot) -> None:
    """[T0102] 잘못된 URL 입력 시 네트워크 호출 없이 '지원하지 않는 URL' 토스트가 뜨고 입력칸이 비워지는지 검증."""
    with patch("chzzk_downloader.gui.main_window.VodCheckWorker") as mock_worker:
        main_window.url_input.setText("https://invalid-url.com/abc")
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

        mock_worker.assert_not_called()
        assert main_window.url_input.text() == ""
        assert main_window.toast.isHidden() is False
        assert "Invalid:" in main_window.toast.label.text()
        assert main_window.toast._timer.isActive() is True


@pytest.mark.ticket("T0102")
def test_invalid_url_toast_dismissed_on_click(main_window, qtbot) -> None:
    """[T0102] 잘못된 URL로 발생한 토스트를 클릭했을 때 사라지는지 검증."""
    main_window.url_input.setText("https://not-chzzk.com/12345")
    qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

    assert main_window.toast.isHidden() is False
    qtbot.mouseClick(main_window.toast, Qt.MouseButton.LeftButton)
    assert main_window.toast.isHidden() is True


@pytest.mark.ticket("T0102")
def test_url_input_enter_key_triggers_download(main_window, qtbot) -> None:
    """[T0102] URL 입력창 활성화 상태에서 Enter 키 입력 시 다운로드 트리거 및 입력칸 비움 검증."""
    with patch("chzzk_downloader.gui.main_window.VodCheckWorker"):
        main_window.url_input.setText("invalid_url_enter_test")
        qtbot.keyClick(main_window.url_input, Qt.Key.Key_Return)

        assert main_window.url_input.text() == ""
        assert main_window.toast.isHidden() is False
        assert "Invalid:" in main_window.toast.label.text()


@pytest.mark.ticket("T0102")
def test_url_input_context_menu_items_and_paste_download(main_window, qtbot) -> None:
    """[T0102] URL 입력칸 우클릭 컨텍스트 메뉴 항목 구성 및 '붙여넣고 다운로드' 동작 검증."""
    menu = main_window._create_url_context_menu()
    actions = [action.text() for action in menu.actions() if not action.isSeparator()]

    expected_actions = [
        "실행 취소",
        "다시 실행",
        "잘라내기",
        "복사",
        "붙여넣기",
        "붙여넣고 다운로드",
        "삭제",
        "모두 선택",
    ]
    assert actions == expected_actions

    clipboard = QApplication.clipboard()
    assert clipboard is not None
    test_url = "https://chzzk.naver.com/video/15016450"
    clipboard.setText(test_url)

    mock_vod = VodInfo(
        video_no="15016450",
        video_title="컨텍스트 메뉴 테스트",
        channel_name="채널B",
    )
    with patch("chzzk_downloader.gui.workers.extract_vod_info", return_value=mock_vod):
        main_window._on_paste_and_download()

        assert main_window.url_input.text() == ""
        assert not main_window.toast.isHidden()
        assert "+" in main_window.toast.label.text()
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)


@pytest.mark.ticket("T0102")
def test_url_input_context_menu_delete_action(main_window) -> None:
    """[T0102] 컨텍스트 메뉴의 '삭제' 기능이 선택된 텍스트만 삭제하는지 검증."""
    main_window.url_input.setText("hello world")
    main_window.url_input.setSelection(6, 5)

    menu = main_window._create_url_context_menu()
    delete_action = next(a for a in menu.actions() if a.text() == "삭제")
    assert delete_action.isEnabled() is True

    delete_action.trigger()
    assert main_window.url_input.text() == "hello "


@pytest.mark.ticket("T0102")
def test_url_input_show_context_menu_non_modal(main_window) -> None:
    """[T0102] 우클릭 시 메뉴가 non-modal(popup)로 호출되는지 검증."""
    main_window._show_url_context_menu(QPoint(10, 10))
    assert main_window._url_context_menu is not None
    assert main_window._url_context_menu.isVisible()
    main_window._url_context_menu.close()


@pytest.mark.ticket("T0102")
def test_new_download_request_dismisses_previous_toast(main_window, qtbot) -> None:
    """[T0102] 새로운 다운로드 버튼 클릭 시 이전 토스트가 즉시 사라지는지 검증."""
    # 1. 먼저 잘못된 URL로 에러 토스트 띄우기
    main_window.url_input.setText("invalid_url_1")
    qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)
    assert main_window.toast.isHidden() is False

    # 2. 다른 정상 URL 입력 후 클릭 시 이전 토스트 dismiss 후 새로운 상태 반영 확인
    mock_vod = VodInfo(
        video_no="15016450",
        video_title="실제 테스트 방송",
        channel_name="테스트채널",
    )
    with patch("chzzk_downloader.gui.workers.extract_vod_info", return_value=mock_vod):
        main_window.url_input.setText("https://chzzk.naver.com/video/15016450")
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

        assert main_window.url_input.text() == ""
        assert not main_window.toast.isHidden()
        assert "+" in main_window.toast.label.text()
        assert "15016450" in main_window.toast.label.text()
        assert main_window.toast._timer.isActive() is True
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)
