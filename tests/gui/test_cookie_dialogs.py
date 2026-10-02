"""쿠키 뷰어 다이얼로그 및 네이버 웹뷰 로그인 창 상호작용 GUI 테스트."""

from unittest.mock import patch

import pytest
from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtNetwork import QNetworkCookie
from PyQt6.QtWidgets import QMessageBox

from chzzk_downloader.core.cookie_manager import (
    get_cookie_file_path,
    get_cookies_text,
    has_valid_cookies,
    save_cookies_text,
    save_network_cookies,
)
from chzzk_downloader.gui.cookie_viewer_dialog import CookieViewerDialog
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.naver_login_dialog import NaverLoginDialog
from chzzk_downloader.gui.task_card import TaskCardWidget, TaskStatus


@pytest.fixture
def main_window(qtbot):
    """메인 창 인스턴스를 생성하고 표시하는 fixture."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    return window


@pytest.mark.ticket("T0106")
def test_cookie_viewer_dialog_save_and_cancel(qtbot) -> None:
    """[T0106] CookieViewerDialog에서 텍스트 입력 후 저장 및 취소 동작 검증."""
    dialog = CookieViewerDialog()
    qtbot.addWidget(dialog)

    # 1. 유효하지 않은 입력 시 저장 거부 및 에러 피드백
    dialog.text_edit.setPlainText("OTHER_KEY=value_without_nid")
    dialog._on_save_clicked()
    assert dialog.feedback_label.isHidden() is False
    assert "필수 쿠키" in dialog.feedback_label.text()

    # 2. 유효한 입력 시 저장 성공
    dialog.text_edit.setPlainText("NID_AUT=modal_aut; NID_SES=modal_ses")
    with qtbot.waitSignal(dialog.accepted, timeout=1000):
        dialog._on_save_clicked()

    assert has_valid_cookies() is True
    assert "NID_AUT\tmodal_aut" in get_cookies_text()


@pytest.mark.ticket("T0106")
def test_task_card_auth_buttons_distinct_actions(main_window, qtbot) -> None:
    """[T0106] 로그인 필요 카드의 [쿠키 설정]은 설정창을 열고, [네이버 로그인]은 로그인 다이얼로그를 트리거하는지 검증."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/19000",
        status=TaskStatus.FAILED_LOGIN_REQUIRED,
    )
    main_window.task_list_widget.add_task_card(card)

    # 1. [쿠키 설정] 클릭 -> Modeless 설정 창 열림
    qtbot.mouseClick(card.cookie_btn, Qt.MouseButton.LeftButton)
    assert main_window._settings_window is not None
    assert main_window._settings_window.isVisible() is True
    main_window._settings_window.close()

    # 2. [네이버 로그인] 클릭 -> request_naver_login 시그널 방출 및 NaverLoginDialog.exec 호출 검증
    with patch(
        "chzzk_downloader.gui.naver_login_dialog.NaverLoginDialog.exec"
    ) as mock_exec:
        with qtbot.waitSignal(card.request_naver_login, timeout=1000):
            qtbot.mouseClick(card.login_btn, Qt.MouseButton.LeftButton)
        assert mock_exec.called is True


@pytest.mark.ticket("T0106")
def test_save_network_cookies_and_naver_login_dialog(qtbot) -> None:
    """[T0106] save_network_cookies 함수 및 NaverLoginDialog 쿠키 감지·완료 로직 검증."""
    # 1. save_network_cookies 검증
    cookie_aut = QNetworkCookie(QByteArray(b"NID_AUT"), QByteArray(b"test_net_aut"))
    cookie_aut.setDomain(".naver.com")
    cookie_aut.setPath("/")
    cookie_aut.setSecure(True)

    cookie_ses = QNetworkCookie(QByteArray(b"NID_SES"), QByteArray(b"test_net_ses"))
    cookie_ses.setDomain(".naver.com")
    cookie_ses.setPath("/")

    cookie_other = QNetworkCookie(QByteArray(b"OTHER"), QByteArray(b"val"))
    cookie_other.setDomain(".google.com")

    # 인증 쿠키 없을 때 실패
    ok, err = save_network_cookies([cookie_other])
    assert ok is False
    assert "감지되지 않았습니다" in err

    # 유효 쿠키 저장 성공
    ok, msg = save_network_cookies([cookie_aut, cookie_ses, cookie_other])
    assert ok is True
    assert "저장되었습니다" in msg
    assert has_valid_cookies() is True
    assert "test_net_aut" in get_cookies_text()

    # 2. NaverLoginDialog 이벤트 핸들러 검증
    with patch("PyQt6.QtWebEngineWidgets.QWebEngineView.load"):
        dialog = NaverLoginDialog()
        qtbot.addWidget(dialog)
        assert dialog.save_btn.isEnabled() is False

        # 쿠키 추가 이벤트 시뮬레이션
        dialog._on_cookie_added(cookie_aut)
        assert dialog.save_btn.isEnabled() is True
        assert "인증 정보가 감지되었습니다" in dialog.status_label.text()

        # 저장 및 닫기 호출 시 시그널 방출 확인
        with qtbot.waitSignal(dialog.login_success, timeout=1000):
            dialog._on_save_and_close()


@pytest.mark.ticket("T0106")
def test_naver_login_dialog_cancel_and_double_cleanup(qtbot) -> None:
    """[T0106] 로그인 미완료 상태에서 취소/닫기 시 QWebEngineView 리소스 정리 및 중복 cleanup 안전성 검증."""
    with patch("PyQt6.QtWebEngineWidgets.QWebEngineView.load"):
        dialog = NaverLoginDialog()
        qtbot.addWidget(dialog)

        # 1. 미완료 상태에서 reject 호출
        dialog.reject()
        assert dialog.result() == 0

        # 2. _cleanup() 중복 호출 시 예외 발생하지 않는지 검증
        dialog._cleanup()
        dialog._cleanup()

        # 쿠키 파일이 생성되지 않았는지 확인
        assert has_valid_cookies() is False


@pytest.mark.ticket("T0106")
def test_naver_login_dialog_ignore_irrelevant_cookies(qtbot) -> None:
    """[T0106] 타 도메인 쿠키 또는 필수 인증 쿠키(NID_AUT/NID_SES)가 누락된 일반 쿠키 유입 시 저장 차단 검증."""
    with patch("PyQt6.QtWebEngineWidgets.QWebEngineView.load"):
        dialog = NaverLoginDialog()
        qtbot.addWidget(dialog)

        # 1. 구글 도메인 쿠키 유입
        google_cookie = QNetworkCookie(QByteArray(b"SID"), QByteArray(b"google_val"))
        google_cookie.setDomain(".google.com")
        dialog._on_cookie_added(google_cookie)
        assert dialog.save_btn.isEnabled() is False

        # 2. 네이버 도메인이지만 일반 비인증 쿠키 유입
        naver_misc_cookie = QNetworkCookie(
            QByteArray(b"NNB"), QByteArray(b"random_nnb")
        )
        naver_misc_cookie.setDomain(".naver.com")
        dialog._on_cookie_added(naver_misc_cookie)
        assert dialog.save_btn.isEnabled() is False

        # 3. 필수 인증 쿠키 없는 상태에서 _on_save_and_close 호출 시 저장 방어
        with patch.object(QMessageBox, "warning") as mock_warn:
            dialog._on_save_and_close()
            assert mock_warn.called is True
            assert has_valid_cookies() is False


@pytest.mark.ticket("PR08")
def test_naver_login_dialog_plan_a_single_cookie_does_not_overwrite_existing(
    qtbot,
) -> None:
    """[PR08] 단일 쿠키 수집 이벤트 발생 시 디스크 파일이 조기 덮어써지지 않고, 로그인 확정 시에만 저장되는지 검증 (방안 A)."""
    cookie_file = get_cookie_file_path()
    save_cookies_text("NID_AUT=orig_aut_value; NID_SES=orig_ses_value")
    orig_content = cookie_file.read_text(encoding="utf-8")
    assert "orig_aut_value" in orig_content
    assert "orig_ses_value" in orig_content

    with patch("PyQt6.QtWebEngineWidgets.QWebEngineView.load"):
        dialog = NaverLoginDialog()
        qtbot.addWidget(dialog)

        cookie_aut = QNetworkCookie(
            QByteArray(b"NID_AUT"), QByteArray(b"new_aut_value")
        )
        cookie_aut.setDomain(".naver.com")
        cookie_aut.setPath("/")
        dialog._on_cookie_added(cookie_aut)

        # NID_AUT 감지 시 save_btn은 활성화될 수 있지만
        # 디스크의 파일은 로그인 완료/저장을 누르기 전까지 절대 조기 저장되지 않아야 함!
        current_disk_content = cookie_file.read_text(encoding="utf-8")
        assert current_disk_content == orig_content
        assert "new_aut_value" not in current_disk_content

        dialog.reject()
        assert cookie_file.read_text(encoding="utf-8") == orig_content

    with patch("PyQt6.QtWebEngineWidgets.QWebEngineView.load"):
        dialog2 = NaverLoginDialog()
        qtbot.addWidget(dialog2)

        cookie_aut = QNetworkCookie(QByteArray(b"NID_AUT"), QByteArray(b"new_aut_111"))
        cookie_aut.setDomain(".naver.com")
        cookie_aut.setPath("/")
        dialog2._on_cookie_added(cookie_aut)

        cookie_ses = QNetworkCookie(QByteArray(b"NID_SES"), QByteArray(b"new_ses_222"))
        cookie_ses.setDomain(".naver.com")
        cookie_ses.setPath("/")
        dialog2._on_cookie_added(cookie_ses)

        assert dialog2.save_btn.isEnabled() is True
        assert cookie_file.read_text(encoding="utf-8") == orig_content

        dialog2._on_save_and_close()

        final_disk_content = cookie_file.read_text(encoding="utf-8")
        assert "new_aut_111" in final_disk_content
        assert "new_ses_222" in final_disk_content
