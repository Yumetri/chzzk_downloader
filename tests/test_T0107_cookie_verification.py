"""T0107. 앱 시작 시 쿠키 세션 검증 및 쿠키 삭제 단위/통합 테스트."""

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QMessageBox

from chzzk_downloader.core.cookie_manager import (
    SessionStatus,
    get_cookie_status_summary,
    get_last_session_status,
    has_valid_cookies,
    save_cookies_text,
    verify_cookie_session,
)
from chzzk_downloader.core.ytdlp import VodInfo
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.task_card import TaskCardWidget, TaskStatus
from chzzk_downloader.gui.toast import ToastWidget
from chzzk_downloader.gui.workers import CookieVerifyWorker


@pytest.fixture
def setup_test_cookie_path(tmp_path, monkeypatch):
    """임시 디렉터리의 쿠키 경로를 사용하도록 설정하는 fixture."""
    test_cookie_file = tmp_path / "test_cookies.txt"
    monkeypatch.setattr(
        "chzzk_downloader.core.cookie_manager.get_cookie_file_path",
        lambda: test_cookie_file,
    )
    return test_cookie_file


def test_verify_cookie_session_no_cookies(setup_test_cookie_path):
    """쿠키 파일이 없거나 비어있는 경우 NO_COOKIES 반환 검증."""
    status, msg = verify_cookie_session()
    assert status == SessionStatus.NO_COOKIES
    assert "등록된 쿠키 없음" in msg


def test_verify_cookie_session_valid_200(setup_test_cookie_path):
    """치지직 API 200 OK 및 닉네임 반환 시 VALID 상태 및 최근 확인 시각 갱신 검증."""
    save_cookies_text("NID_AUT=aut_valid; NID_SES=ses_valid")

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"code": 200, "content": {"nickname": "치지직유저"}}
    ).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        status, msg = verify_cookie_session()
        assert status == SessionStatus.VALID
        assert "치지직유저" in msg
        assert "최근 확인" in msg

        # get_cookie_status_summary에도 반영 확인
        summary = get_cookie_status_summary()
        assert "치지직유저" in summary


def test_verify_cookie_session_expired_401(setup_test_cookie_path):
    """치지직 API 401 Unauthorized 반환 시 EXPIRED 상태 검증."""
    save_cookies_text("NID_AUT=aut_expired; NID_SES=ses_expired")

    err = urllib.error.HTTPError(
        url="https://comm-api.game.naver.com/nng_main/v1/user/getUserStatus",
        code=401,
        msg="Unauthorized",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"code": 401, "message": "Unauthorized"}'),
    )

    with patch("urllib.request.urlopen", side_effect=err):
        status, msg = verify_cookie_session()
        assert status == SessionStatus.EXPIRED
        assert "만료됨" in msg

        # 요약에도 만료 반영 확인
        summary = get_cookie_status_summary()
        assert "만료됨" in summary


def test_verify_cookie_session_logged_in_false(setup_test_cookie_path):
    """API 응답은 200이나 loggedIn이 false인 경우 세션 만료(EXPIRED) 처리 검증."""
    save_cookies_text("NID_AUT=aut_expired; NID_SES=ses_expired")

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"code": 200, "content": {"loggedIn": False, "nickname": None}}
    ).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        status, msg = verify_cookie_session()
        assert status == SessionStatus.EXPIRED
        assert "만료됨" in msg

        summary = get_cookie_status_summary()
        assert "만료됨" in summary


def test_verify_cookie_session_network_error(setup_test_cookie_path):
    """타임아웃 또는 네트워크 연결 불가 시 NETWORK_ERROR 상태 반환 검증."""
    save_cookies_text("NID_AUT=aut_val; NID_SES=ses_val")

    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("Connection refused"),
    ):
        status, msg = verify_cookie_session()
        assert status == SessionStatus.NETWORK_ERROR
        assert "네트워크 연결 실패" in msg


def test_cookie_verify_worker_thread(setup_test_cookie_path, qtbot):
    """CookieVerifyWorker QThread가 백그라운드에서 실행되고 시그널을 방출하는지 검증."""
    save_cookies_text("NID_AUT=worker_aut; NID_SES=worker_ses")

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"code": 200, "content": {"nickname": "워커테스터"}}
    ).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        worker = CookieVerifyWorker(timeout=2.0)
        with qtbot.waitSignal(worker.finished_verification, timeout=2000) as blocker:
            worker.start()

        status, msg = blocker.args
        assert status == SessionStatus.VALID
        assert "워커테스터" in msg


def test_toast_action_buttons_and_order(qtbot):
    """ToastWidget 액션 토스트 내 버튼 순서([쿠키 설정] -> [네이버 로그인] -> [✕]) 및 콜백 동작 검증."""
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


def test_main_window_startup_verification_expired_shows_action_toast(
    setup_test_cookie_path, qtbot
):
    """메인 창 기동 시 만료된 쿠키(401)가 있을 때 액션 토스트 노출 및 다이얼로그 연동 검증."""
    save_cookies_text("NID_AUT=expired_aut; NID_SES=expired_ses")

    err = urllib.error.HTTPError(
        url="https://comm-api.game.naver.com/nng_main/v1/user/getUserStatus",
        code=401,
        msg="Unauthorized",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"code": 401}'),
    )

    with patch("urllib.request.urlopen", side_effect=err):
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()

        # 워커 종료 및 액션 토스트 노출 대기
        qtbot.waitUntil(lambda: window.toast.isHidden() is False, timeout=2000)
        assert window.toast._is_action_mode is True
        assert "만료되었습니다" in window.toast.label.text()
        assert len(window.toast._action_buttons) == 2

        # [쿠키 설정] 버튼 클릭 -> Modeless 설정 창 오픈 검증
        window.toast._action_buttons[0].click()
        assert window.toast.isHidden() is True
        assert window._settings_window is not None
        assert window._settings_window.isVisible() is True
        window._settings_window.close()


def test_main_window_startup_verification_valid_silent(setup_test_cookie_path, qtbot):
    """메인 창 기동 시 정상 인증(200 OK) 쿠키일 때 토스트 없이 정숙(침묵) 유지 검증."""
    save_cookies_text("NID_AUT=aut_valid; NID_SES=ses_valid")

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"code": 200, "content": {"nickname": "정상유저"}}
    ).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()

        if window._cookie_verify_worker:
            qtbot.waitUntil(
                lambda: not window._cookie_verify_worker.isRunning(), timeout=2000
            )

        # 토스트가 뜨지 않고 숨김 상태 유지
        assert window.toast.isHidden() is True

        # 최근 세션 상태는 VALID
        status, msg = get_last_session_status()
        assert status == SessionStatus.VALID
        assert "정상유저" in msg


def test_cookie_deletion_preserves_existing_task_cards(setup_test_cookie_path, qtbot):
    """쿠키 삭제(초기화) 시 기존에 목록에 추가된 작업 카드가 훼손되지 않고 온전히 보존되는지 검증."""
    save_cookies_text("NID_AUT=test_aut; NID_SES=test_ses")

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"code": 200, "content": {}}).encode(
        "utf-8"
    )
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()

        if window._cookie_verify_worker:
            qtbot.waitUntil(
                lambda: not window._cookie_verify_worker.isRunning(), timeout=2000
            )

        # 1. 기존 작업 카드 추가
        card1 = TaskCardWidget(
            raw_url="https://chzzk.naver.com/video/11111",
            status=TaskStatus.READY,
            vod_info=VodInfo(
                video_no="11111",
                video_title="기존 완료 영상 1",
                channel_name="테스트채널",
            ),
        )
        window.task_list_widget.add_task_card(card1)

        card2 = TaskCardWidget(
            raw_url="https://chzzk.naver.com/video/22222",
            status=TaskStatus.FAILED_LOGIN_REQUIRED,
        )
        window.task_list_widget.add_task_card(card2)

        assert window.task_list_widget.list_widget.count() == 2

        # 2. 설정 창 열고 쿠키 삭제([초기화]) 실행
        window._on_settings_clicked()
        settings_win = window._settings_window
        assert settings_win is not None

        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            with patch.object(QMessageBox, "information"):
                settings_win._on_clear_clicked()

        # 3. 검증: 쿠키는 삭제됨
        assert has_valid_cookies() is False
        assert "등록된 쿠키 없음" in settings_win.status_label.text()

        # 4. 중요: 기존 카드는 삭제되지 않고 2개 모두 그대로 유지됨
        assert window.task_list_widget.list_widget.count() == 2
        cards = window.task_list_widget.get_all_cards()
        assert len(cards) == 2
        assert cards[1].status == TaskStatus.READY
        assert "기존 완료 영상 1" in cards[1].title_label.text()
        assert cards[0].status == TaskStatus.FAILED_LOGIN_REQUIRED
        window.close()
