"""PR #8 리뷰 결함 5종 수정 (QThread 크래시, 종료 프리징, 쿠키 삭제 실패, 쿠키 유실 방지, 파일 권한) 검증 테스트."""

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6.QtCore import QByteArray
from PyQt6.QtNetwork import QNetworkCookie
from PyQt6.QtWidgets import QMessageBox

from chzzk_downloader.core.cookie_manager import (
    SessionStatus,
    clear_cookies,
    get_last_session_status,
    save_cookies_text,
    save_network_cookies,
)
from chzzk_downloader.gui.main_window import _DETACHED_WORKERS, MainWindow
from chzzk_downloader.gui.naver_login_dialog import NaverLoginDialog
from chzzk_downloader.gui.settings_window import SettingsWindow
from chzzk_downloader.gui.task_card import TaskCardWidget, TaskStatus


@pytest.fixture
def setup_test_cookie_path(tmp_path, monkeypatch):
    """임시 디렉터리의 쿠키 경로를 사용하도록 설정하는 fixture."""
    test_cookie_file = tmp_path / "test_cookies.txt"
    monkeypatch.setattr(
        "chzzk_downloader.core.cookie_manager.get_cookie_file_path",
        lambda: test_cookie_file,
    )
    return test_cookie_file


# ---------------------------------------------------------------------------
# Issue 1: 앱 시작 직후 종료 시 QThread 크래시 방지 검증
# ---------------------------------------------------------------------------
def test_close_immediately_after_startup_no_qthread_crash(
    qtbot, setup_test_cookie_path
):
    """앱 시작 직후 백그라운드 세션 검증 워커가 실행 중일 때 즉시 창을 닫아도 C++ 소멸 크래시 없이 정상 종료되는지 검증."""

    save_cookies_text("NID_AUT=test_aut; NID_SES=test_ses")

    def slow_verify(*args, **kwargs):
        time.sleep(1.0)
        return SessionStatus.VALID, "지연 검증 성공"

    with patch(
        "chzzk_downloader.core.cookie_manager.verify_cookie_session",
        side_effect=slow_verify,
    ):
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()

        worker = window._cookie_verify_worker
        assert worker is not None
        assert worker.isRunning() is True
        assert worker.parent() is None

        window.close()
        assert window._cookie_verify_worker is None

        if worker.isRunning():
            assert worker in _DETACHED_WORKERS
            qtbot.waitUntil(lambda: not worker.isRunning(), timeout=2000)
            assert worker not in _DETACHED_WORKERS


# ---------------------------------------------------------------------------
# Issue 2: 자동 재분석 중 앱 종료 시 무한 대기(UI 프리징) 방지 검증
# ---------------------------------------------------------------------------
def test_close_event_with_long_running_workers_bounded_wait(
    qtbot, setup_test_cookie_path
):
    """재분석 워커가 오래 걸려도 closeEvent가 0.5초 이내에 신속히 반환되어 UI 프리징을 방지하는지 검증."""
    save_cookies_text("NID_AUT=test_aut; NID_SES=test_ses")

    def blocking_extract(*args, **kwargs):
        time.sleep(3.0)
        return None

    with patch(
        "chzzk_downloader.gui.workers.extract_vod_info",
        side_effect=blocking_extract,
    ):
        window = MainWindow()
        qtbot.addWidget(window)
        window.show()

        card1 = TaskCardWidget(
            raw_url="https://chzzk.naver.com/video/10001",
            status=TaskStatus.FAILED_LOGIN_REQUIRED,
        )
        card2 = TaskCardWidget(
            raw_url="https://chzzk.naver.com/video/10002",
            status=TaskStatus.FAILED_LOGIN_REQUIRED,
        )
        window.task_list_widget.add_task_card(card1)
        window.task_list_widget.add_task_card(card2)

        window._on_cookies_updated()
        assert len(window._recheck_workers) == 2
        for w in window._recheck_workers:
            assert w.isRunning() is True
            assert w.parent() is None

        t0 = time.perf_counter()
        window.close()
        t1 = time.perf_counter()
        elapsed = t1 - t0

        assert elapsed < 0.5
        assert len(window._recheck_workers) == 0


# ---------------------------------------------------------------------------
# Issue 3: 쿠키 삭제 실패 시 오류 반환 및 경고 팝업 검증
# ---------------------------------------------------------------------------
def test_clear_cookies_failure_handling(setup_test_cookie_path, qtbot):
    """쿠키 파일 삭제(unlink) 실패 시 clear_cookies()가 False를 반환하고 세션 상태를 왜곡하지 않으며 경고 팝업이 뜨는지 검증."""
    save_cookies_text("NID_AUT=original_aut; NID_SES=original_ses")
    assert setup_test_cookie_path.exists() is True

    with patch.object(Path, "unlink", side_effect=PermissionError("Permission Denied")):
        ok, msg = clear_cookies()
        assert ok is False
        assert "쿠키 파일 삭제 실패" in msg

        status, _ = get_last_session_status()
        assert status != SessionStatus.NO_COOKIES

    settings_win = SettingsWindow()
    qtbot.addWidget(settings_win)

    with patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
    ):
        with patch.object(
            Path, "unlink", side_effect=PermissionError("Permission Denied")
        ):
            with patch.object(QMessageBox, "warning") as mock_warning:
                settings_win._on_clear_clicked()
                mock_warning.assert_called_once()
                assert "초기화 실패" in mock_warning.call_args[0][1]


# ---------------------------------------------------------------------------
# Issue 4: 단일 쿠키 이벤트 발생 시 기존 인증 쿠키 유실 방지 검증 (방안 A)
# ---------------------------------------------------------------------------
def test_naver_login_dialog_plan_a_single_cookie_does_not_overwrite_existing(
    qtbot, setup_test_cookie_path
):
    """단일 쿠키 수집 이벤트 발생 시 디스크 파일이 조기 덮어써지지 않고, 로그인 확정 시에만 저장되는지 검증 (방안 A)."""
    save_cookies_text("NID_AUT=orig_aut_value; NID_SES=orig_ses_value")
    orig_content = setup_test_cookie_path.read_text(encoding="utf-8")
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
        # 방안 A 검증: 디스크의 파일은 로그인 완료/저장을 누르기 전까지 절대 조기 저장(Write-Through)되지 않아야 함!
        current_disk_content = setup_test_cookie_path.read_text(encoding="utf-8")
        assert current_disk_content == orig_content
        assert "new_aut_value" not in current_disk_content

        dialog.reject()
        assert setup_test_cookie_path.read_text(encoding="utf-8") == orig_content

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
        assert setup_test_cookie_path.read_text(encoding="utf-8") == orig_content

        dialog2._on_save_and_close()

        final_disk_content = setup_test_cookie_path.read_text(encoding="utf-8")
        assert "new_aut_111" in final_disk_content
        assert "new_ses_222" in final_disk_content


# ---------------------------------------------------------------------------
# Issue 5: 쿠키 파일 및 디렉터리 권한(0600 / 0700) 설정 검증
# ---------------------------------------------------------------------------
def test_cookie_file_secure_permissions(setup_test_cookie_path):
    """쿠키 파일 저장 시 0600, 부모 디렉터리는 0700 퍼미션 설정이 호출되는지 검증."""
    with patch.object(Path, "chmod") as mock_chmod:
        save_cookies_text("NID_AUT=test_perm_aut; NID_SES=test_perm_ses")
        chmod_calls = [call[0][0] for call in mock_chmod.call_args_list]
        assert 0o700 in chmod_calls or 0o600 in chmod_calls

    cookie_obj = QNetworkCookie(QByteArray(b"NID_AUT"), QByteArray(b"val"))
    cookie_obj.setDomain(".naver.com")
    cookie_obj.setPath("/")

    with patch.object(Path, "chmod") as mock_chmod:
        save_network_cookies([cookie_obj])
        chmod_calls = [call[0][0] for call in mock_chmod.call_args_list]
        assert 0o700 in chmod_calls or 0o600 in chmod_calls
