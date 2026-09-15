"""오버레이 토스트 위젯 표시, 자동 소멸, 액션 버튼 순서 및 수동 닫기 GUI 테스트."""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from chzzk_downloader.gui.toast import ToastType, ToastWidget


@pytest.fixture
def toast_widget(qtbot):
    """테스트용 부모 위젯 및 ToastWidget 생성 fixture."""
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(400, 300)
    parent.show()
    toast = ToastWidget(parent)
    yield toast


def test_toast_initial_state(toast_widget) -> None:
    """초기 상태에서 토스트가 숨김 상태인지 검증."""
    assert toast_widget.isHidden() is True
    assert toast_widget._timer.isActive() is False


def test_toast_show_success_with_auto_dismiss(toast_widget, qtbot) -> None:
    """성공 토스트 표시 시 지정된 시간 후 자동으로 사라지는지 검증."""
    toast_widget.show_toast("성공 메시지", ToastType.SUCCESS, auto_dismiss_ms=100)
    assert toast_widget.isHidden() is False
    assert toast_widget.label.text() == "성공 메시지"
    assert toast_widget._timer.isActive() is True

    # 100ms 경과 후 자동 소멸 대기
    qtbot.waitUntil(lambda: toast_widget.isHidden(), timeout=500)
    assert toast_widget._timer.isActive() is False


def test_toast_show_error_persists_without_auto_dismiss(toast_widget, qtbot) -> None:
    """auto_dismiss_ms=0인 경우 타이머 없이 계속 유지되는지 검증."""
    toast_widget.show_toast("실패 메시지", ToastType.ERROR, auto_dismiss_ms=0)
    assert toast_widget.isHidden() is False
    assert toast_widget.label.text() == "실패 메시지"
    assert toast_widget._timer.isActive() is False

    # 잠시 대기해도 닫히지 않음
    qtbot.wait(150)
    assert toast_widget.isHidden() is False


def test_toast_click_to_dismiss(toast_widget, qtbot) -> None:
    """토스트 영역 클릭 시 즉시 닫히는지 검증."""
    toast_widget.show_toast("클릭 테스트", ToastType.ERROR, auto_dismiss_ms=0)
    assert toast_widget.isHidden() is False

    # 토스트 위젯 클릭
    qtbot.mouseClick(toast_widget, Qt.MouseButton.LeftButton)
    assert toast_widget.isHidden() is True


@pytest.mark.ticket("T0107")
def test_toast_action_buttons_and_order(qtbot) -> None:
    """[T0107] ToastWidget 액션 토스트 내 버튼 순서([쿠키 설정] -> [네이버 로그인] -> [✕]) 및 콜백 동작 검증."""
    toast = ToastWidget()
    qtbot.addWidget(toast)

    cookie_settings_called = False
    naver_login_called = False

    def on_settings():
        nonlocal cookie_settings_called
        cookie_settings_called = True

    def on_login():
        nonlocal naver_login_called
        naver_login_called = True

    # 액션 토스트 표시 (사용자 지정 순서: [쿠키 설정] -> [네이버 로그인])
    toast.show_action_toast(
        "저장된 네이버 로그인 쿠키가 만료되었습니다.",
        buttons=[
            ("쿠키 설정", "#3b82f6", on_settings),
            ("네이버 로그인", "#03c75a", on_login),
        ],
    )

    assert toast.isHidden() is False
    assert toast._is_action_mode is True
    assert len(toast._action_buttons) == 2

    # 버튼 텍스트 및 순서 확인
    assert toast._action_buttons[0].text() == "쿠키 설정"
    assert toast._action_buttons[1].text() == "네이버 로그인"

    # 1. [쿠키 설정] 클릭 -> 콜백 호출 및 토스트 닫힘 확인
    toast._action_buttons[0].click()
    assert cookie_settings_called is True
    assert toast.isHidden() is True

    # 2. 다시 띄우고 [네이버 로그인] 클릭 확인
    toast.show_action_toast(
        "저장된 네이버 로그인 쿠키가 만료되었습니다.",
        buttons=[
            ("쿠키 설정", "#3b82f6", on_settings),
            ("네이버 로그인", "#03c75a", on_login),
        ],
    )
    toast._action_buttons[1].click()
    assert naver_login_called is True
    assert toast.isHidden() is True

    # 3. 다시 띄우고 [✕] 버튼 클릭 시 닫힘 확인
    toast.show_action_toast(
        "저장된 네이버 로그인 쿠키가 만료되었습니다.",
        buttons=[
            ("쿠키 설정", "#3b82f6", on_settings),
            ("네이버 로그인", "#03c75a", on_login),
        ],
    )
    toast.close_btn.click()
    assert toast.isHidden() is True
