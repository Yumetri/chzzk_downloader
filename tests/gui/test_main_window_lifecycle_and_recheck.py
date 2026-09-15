"""메인 윈도우 수명주기, 기동 시 세션 검증, 쿠키 변경 시 자동 재분석 및 종료 이벤트 처리 GUI 테스트."""

import io
import json
import time
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from chzzk_downloader.config import SUCCESS_TOAST_DURATION_MS
from chzzk_downloader.core.cookie_manager import (
    SessionStatus,
    get_last_session_status,
    has_valid_cookies,
    save_cookies_text,
)
from chzzk_downloader.core.ytdlp import (
    VodFormatInfo,
    VodInfo,
    VodNotFoundError,
    YtDlpError,
)
from chzzk_downloader.gui.main_window import _DETACHED_WORKERS, MainWindow
from chzzk_downloader.gui.task_card import TaskCardWidget, TaskStatus


@pytest.fixture
def main_window(qtbot):
    """메인 창 인스턴스를 생성하고 표시하는 fixture."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    return window


@pytest.mark.ticket("T0102")
def test_valid_url_success_flow_and_input_cleared(main_window, qtbot) -> None:
    """[T0102] 정상 VOD URL 입력 시 입력칸 비움, '+ [URL]' 토스트 2초 타이머 노출 검증."""
    mock_vod = VodInfo(
        video_no="15016450",
        video_title="치지직 테스트 방송 다시보기",
        channel_name="채널A",
    )

    with patch("chzzk_downloader.gui.workers.extract_vod_info", return_value=mock_vod):
        test_url = "https://chzzk.naver.com/video/15016450"
        main_window.url_input.setText(f"  {test_url} \n")
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

        assert main_window.url_input.text() == ""
        assert main_window.toast.isHidden() is False
        text = main_window.toast.label.text()
        assert "+" in text
        assert test_url in text

        assert main_window.toast._timer.isActive() is True
        assert main_window.toast._timer.interval() == SUCCESS_TOAST_DURATION_MS

        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)
        assert "+" in main_window.toast.label.text()
        assert test_url in main_window.toast.label.text()


@pytest.mark.ticket("T0102")
def test_valid_url_not_found_failure_flow(main_window, qtbot) -> None:
    """[T0102] 존재하지 않는 VOD URL 입력 시 실패 토스트가 유지되는지 검증."""
    with patch(
        "chzzk_downloader.gui.workers.extract_vod_info",
        side_effect=VodNotFoundError("동영상 정보가 존재하지 않습니다."),
    ):
        main_window.url_input.setText("https://chzzk.naver.com/video/99999999")
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

        assert main_window.url_input.text() == ""

        qtbot.waitUntil(
            lambda: "Invalid:" in main_window.toast.label.text(), timeout=2000
        )
        assert "99999999" in main_window.toast.label.text()
        assert main_window.toast._timer.isActive() is True
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)


@pytest.mark.ticket("T0106")
def test_main_window_auto_reanalyze_failed_login_cards_on_cookie_update(
    main_window, qtbot
) -> None:
    """[T0106] 쿠키 등록 완료 시 로그인 필요 실패 카드들이 자동으로 재분석되는지 검증."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15021267",
        status=TaskStatus.FAILED_LOGIN_REQUIRED,
    )
    main_window.task_list_widget.add_task_card(card)
    assert card.status == TaskStatus.FAILED_LOGIN_REQUIRED

    save_cookies_text("NID_AUT=auto_reanalyze_aut; NID_SES=auto_reanalyze_ses")

    mock_vod = VodInfo(
        video_no="15021267",
        video_title="성인 인증 완료 방송",
        channel_name="스트리머D",
        duration=3600,
        formats=[VodFormatInfo(format_id="1080p", height=1080, fps=60.0)],
        live_open_date="2024-05-06",
    )

    with patch("chzzk_downloader.gui.workers.extract_vod_info", return_value=mock_vod):
        main_window._on_cookies_updated()

        assert main_window.toast.isHidden() is True

        qtbot.waitUntil(
            lambda: card.status in (TaskStatus.READY, TaskStatus.DOWNLOADING),
            timeout=2000,
        )
        assert card.title_label.text() == "[스트리머D] 2024-05-06 성인 인증 완료 방송"


@pytest.mark.ticket("T0107")
def test_main_window_startup_verification_expired_shows_action_toast(qtbot) -> None:
    """[T0107] 메인 창 기동 시 만료된 쿠키(401)가 있을 때 액션 토스트 노출 및 다이얼로그 연동 검증."""
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

        qtbot.waitUntil(lambda: window.toast.isHidden() is False, timeout=2000)
        assert window.toast._is_action_mode is True
        assert "쿠키를 갱신하세요" in window.toast.label.text()
        assert len(window.toast._action_buttons) == 2
        assert window.toast._action_buttons[0].text() == "🍪"
        assert window.toast._action_buttons[1].text() == "N"

        window.toast._action_buttons[0].click()
        assert window.toast.isHidden() is True
        assert window._settings_window is not None
        assert window._settings_window.isVisible() is True
        window._settings_window.close()


@pytest.mark.ticket("T0107")
def test_main_window_startup_verification_valid_silent(qtbot) -> None:
    """[T0107] 메인 창 기동 시 정상 인증(200 OK) 쿠키일 때 토스트 없이 정숙 유지 검증."""
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

        assert window.toast.isHidden() is True

        status, msg = get_last_session_status()
        assert status == SessionStatus.VALID
        assert "정상유저" in msg


@pytest.mark.ticket("T0107")
def test_cookie_deletion_preserves_existing_task_cards(qtbot) -> None:
    """[T0107] 쿠키 삭제(초기화) 시 기존에 목록에 추가된 작업 카드가 훼손되지 않고 온전히 보존되는지 검증."""
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

        window._on_settings_clicked()
        settings_win = window._settings_window
        assert settings_win is not None

        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            with patch.object(QMessageBox, "information"):
                settings_win._on_clear_clicked()

        assert has_valid_cookies() is False
        assert "등록된 쿠키 없음" in settings_win.status_label.text()

        assert window.task_list_widget.list_widget.count() == 2
        cards = window.task_list_widget.get_all_cards()
        assert len(cards) == 2
        assert cards[1].status == TaskStatus.READY
        assert "기존 완료 영상 1" in cards[1].title_label.text()
        assert cards[0].status == TaskStatus.FAILED_LOGIN_REQUIRED
        window.close()


@pytest.mark.ticket("T0106")
def test_close_immediately_after_startup_no_qthread_crash(qtbot) -> None:
    """[T0106] 앱 시작 직후 백그라운드 세션 검증 워커가 실행 중일 때 즉시 창을 닫아도 크래시 없이 정상 종료되는지 검증."""
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


@pytest.mark.ticket("T0106")
def test_close_event_with_long_running_workers_bounded_wait(qtbot) -> None:
    """[T0106] 재분석 워커가 오래 걸려도 closeEvent가 신속히 반환되어 UI 프리징을 방지하는지 검증."""
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


@pytest.mark.ticket("T0106")
def test_merge_blocker_recheck_worker_card_deleted_before_success(
    main_window, qtbot
) -> None:
    """[T0106] 쿠키 갱신 후 자동 재분석 중 카드를 삭제했을 때 성공 응답 도착 시 크래시 없이 안전하게 무시되는지 검증."""
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
        main_window._on_cookies_updated()
        assert card.status == TaskStatus.ANALYZING
        assert len(main_window._recheck_workers) == 1

        card.delete_btn.click()
        assert main_window.task_list_widget.list_widget.count() == 0

        qtbot.waitUntil(lambda: len(main_window._recheck_workers) == 0, timeout=2000)
        assert main_window.task_list_widget.list_widget.count() == 0


@pytest.mark.ticket("T0106")
def test_merge_blocker_recheck_worker_card_deleted_before_failure(
    main_window, qtbot
) -> None:
    """[T0106] 자동 재분석 중 카드를 삭제했을 때 실패 응답이 늦게 도착해도 크래시 없이 무시되는지 검증."""
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

        card.delete_btn.click()
        assert main_window.task_list_widget.list_widget.count() == 0

        qtbot.waitUntil(lambda: len(main_window._recheck_workers) == 0, timeout=2000)
        assert main_window.task_list_widget.list_widget.count() == 0


@pytest.mark.ticket("T0106")
def test_merge_blocker_main_window_close_event_with_running_recheck_workers(
    main_window, qtbot
) -> None:
    """[T0106] 자동 재분석 워커가 백그라운드에서 실행 중일 때 메인 윈도우 닫기(closeEvent) 시 크래시 방지 검증."""
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


@pytest.mark.ticket("T0106")
def test_modeless_settings_window_closed_on_main_window_close(
    main_window, qtbot
) -> None:
    """[T0106] 메인 윈도우가 닫힐 때 열려있던 Modeless 설정 창도 함께 닫히는지 검증."""
    main_window._on_settings_clicked()
    assert main_window._settings_window is not None
    assert main_window._settings_window.isVisible() is True

    # 메인 창 닫기
    main_window.close()
    assert main_window._settings_window.isVisible() is False
