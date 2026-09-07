"""T0106. 쿠키 관리 및 네이버 로그인 예외 상황 (Merge Blocker & Edge Cases) 단위/통합 테스트."""

import time
from unittest.mock import patch

import pytest
from PyQt6.QtCore import QByteArray
from PyQt6.QtNetwork import QNetworkCookie
from PyQt6.QtWidgets import QMessageBox

from chzzk_downloader.core.cookie_manager import (
    clear_cookies,
    export_cookie_file,
    has_valid_cookies,
    load_cookie_file,
    save_cookies_text,
)
from chzzk_downloader.core.ytdlp import (
    VodFormatInfo,
    VodInfo,
    YtDlpError,
)
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.naver_login_dialog import NaverLoginDialog
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


@pytest.fixture
def main_window(qtbot, setup_test_cookie_path):
    """메인 창 인스턴스를 생성하고 표시하는 fixture."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    return window


def test_merge_blocker_recheck_worker_card_deleted_before_success(main_window, qtbot):
    """Merge Blocker 1: 쿠키 갱신 후 자동 재분석 중 카드를 삭제했을 때 성공 응답 도착 시 크래시 없이 안전하게 무시되는지 검증."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15021267",
        status=TaskStatus.FAILED_LOGIN_REQUIRED,
    )
    main_window.task_list_widget.add_task_card(card)
    assert main_window.task_list_widget.list_widget.count() == 1

    save_cookies_text("NID_AUT=test_aut_123; NID_SES=test_ses_456")

    mock_vod = VodInfo(
        video_no="15021267",
        video_title="성인 인증 완료 방송",
        channel_name="스트리머D",
        duration=3600,
        formats=[VodFormatInfo(format_id="1080p", height=1080, fps=60.0)],
        live_open_date="2024-05-06",
    )

    def slow_extract(_url):
        time.sleep(0.3)
        return mock_vod

    with patch(
        "chzzk_downloader.gui.workers.extract_vod_info", side_effect=slow_extract
    ):
        # 1. 자동 재분석 트리거
        main_window._on_cookies_updated()
        assert card.status == TaskStatus.ANALYZING
        assert len(main_window._recheck_workers) == 1

        # 2. 워커 동작 도중 카드의 삭제 버튼(✕) 클릭
        card.delete_btn.click()
        assert main_window.task_list_widget.list_widget.count() == 0

        # 3. 워커가 완료될 때까지 대기
        qtbot.waitUntil(lambda: len(main_window._recheck_workers) == 0, timeout=2000)

        # 4. 검증: C++ 객체 참조 에러(RuntimeError) 없이 앱 생존, 카드가 부활하지 않음
        assert main_window.task_list_widget.list_widget.count() == 0


def test_merge_blocker_recheck_worker_card_deleted_before_failure(main_window, qtbot):
    """Merge Blocker 2: 자동 재분석 중 카드를 삭제했을 때 실패 응답(401 등)이 늦게 도착해도 크래시 없이 무시되는지 검증."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15021267",
        status=TaskStatus.FAILED_LOGIN_REQUIRED,
    )
    main_window.task_list_widget.add_task_card(card)

    save_cookies_text("NID_AUT=test_aut_123; NID_SES=test_ses_456")

    def slow_fail(_url):
        time.sleep(0.3)
        raise YtDlpError("HTTP Error 401: Unauthorized")

    with patch("chzzk_downloader.gui.workers.extract_vod_info", side_effect=slow_fail):
        main_window._on_cookies_updated()
        assert card.status == TaskStatus.ANALYZING
        assert len(main_window._recheck_workers) == 1

        # 분석 도중 삭제
        card.delete_btn.click()
        assert main_window.task_list_widget.list_widget.count() == 0

        # 워커 종료 대기
        qtbot.waitUntil(lambda: len(main_window._recheck_workers) == 0, timeout=2000)

        # 오류 토스트나 UI 부활 없이 정상 생존
        assert main_window.task_list_widget.list_widget.count() == 0


def test_merge_blocker_main_window_close_event_with_running_recheck_workers(
    main_window, qtbot
):
    """Merge Blocker 3: 자동 재분석 워커가 백그라운드에서 실행 중일 때 메인 윈도우 닫기(closeEvent) 시 크래시 방지 검증."""
    import threading

    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15021267",
        status=TaskStatus.FAILED_LOGIN_REQUIRED,
    )
    main_window.task_list_widget.add_task_card(card)
    save_cookies_text("NID_AUT=test_aut_123; NID_SES=test_ses_456")

    release_event = threading.Event()

    def cancellable_slow_extract(_url):
        release_event.wait(2.0)
        return None

    with patch(
        "chzzk_downloader.gui.workers.extract_vod_info",
        side_effect=cancellable_slow_extract,
    ):
        main_window._on_cookies_updated()
        assert len(main_window._recheck_workers) == 1
        worker = main_window._recheck_workers[0]
        assert worker.isRunning() is True

        # 워커 종료 신호 후 메인 창 닫기 이벤트 실행
        release_event.set()
        main_window.close()
        worker.wait(1000)

        # closeEvent에 의해 워커가 정리되고 리스트가 비워졌는지 확인
        assert len(main_window._recheck_workers) == 0


def test_naver_login_dialog_cancel_and_double_cleanup(qtbot, setup_test_cookie_path):
    """로그인 미완료 상태에서 취소/닫기 시 QWebEngineView 리소스 정리 및 중복 cleanup 안전성 검증."""
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


def test_naver_login_dialog_ignore_irrelevant_cookies(qtbot, setup_test_cookie_path):
    """타 도메인 쿠키 또는 필수 인증 쿠키(NID_AUT/NID_SES)가 누락된 일반 쿠키 유입 시 저장 차단 검증."""
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


def test_cookie_file_corrupted_and_binary_garbage_handling(
    setup_test_cookie_path, tmp_path
):
    """깨진 파일, 빈 파일, 바이너리 쓰레기 데이터 파일 로드 시 안전한 실패 처리 검증."""
    # 1. 존재하지 않는 파일 로드
    ok, msg = load_cookie_file(tmp_path / "non_existent.txt")
    assert ok is False
    assert "존재하지 않습니다" in msg

    # 2. 빈 파일 로드
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")
    ok, msg = load_cookie_file(empty_file)
    assert ok is False
    assert "비어 있습니다" in msg

    # 3. 임의의 텍스트지만 인증 쿠키가 없는 파일
    no_auth_file = tmp_path / "no_auth.txt"
    no_auth_file.write_text(
        ".naver.com\tTRUE\t/\tTRUE\t2147483647\tOTHER\tvalue\n", encoding="utf-8"
    )
    ok, msg = load_cookie_file(no_auth_file)
    assert ok is False
    assert "NID_AUT" in msg

    # 4. 바이너리 쓰레기 데이터 파일 로드
    binary_file = tmp_path / "garbage.bin"
    binary_file.write_bytes(b"\x00\xff\xfe\x01\x02\x03\x80\x90\xaa\xbb")
    ok, msg = load_cookie_file(binary_file)
    assert ok is False


def test_cookie_manager_clear_cookies_when_already_missing(setup_test_cookie_path):
    """쿠키 파일이 이미 존재하지 않는 상태에서 clear_cookies() 호출 시 예외 없이 안전한지 검증."""
    # 파일이 없는 상태 확인
    assert setup_test_cookie_path.exists() is False

    clear_cookies()
    assert has_valid_cookies() is False


def test_export_cookie_file_permission_error_handling(setup_test_cookie_path, tmp_path):
    """내보내기 경로가 디렉터리이거나 쓰기 실패 시 예외 없이 에러 반환 검증."""
    save_cookies_text("NID_AUT=export_test; NID_SES=export_ses")

    # 대상 경로가 기존 디렉터리인 경우 쓰기 오류 발생
    invalid_target = tmp_path / "some_directory"
    invalid_target.mkdir()

    ok, msg = export_cookie_file(invalid_target)
    assert ok is False
    assert "내보내기 실패" in msg


def test_modeless_settings_window_closed_on_main_window_close(main_window, qtbot):
    """메인 윈도우가 닫힐 때 열려있던 Modeless 설정 창도 함께 닫히는지 검증."""
    main_window._on_settings_clicked()
    assert main_window._settings_window is not None
    assert main_window._settings_window.isVisible() is True

    # 메인 창 닫기
    main_window.close()
    assert main_window._settings_window.isVisible() is False
