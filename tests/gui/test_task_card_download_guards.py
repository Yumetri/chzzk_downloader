"""작업 카드(TaskCard) 다운로드 차단 가드(FFmpeg 미가용, 동일 VOD 중복 차단, 빠른 연타 차단 및 삭제 카드 방어) GUI 테스트."""

import time
from unittest.mock import patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from chzzk_downloader.config import SUCCESS_TOAST_DURATION_MS
from chzzk_downloader.core.settings_manager import update_current_settings
from chzzk_downloader.core.ytdlp import VodFormatInfo, VodInfo, YtDlpError
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.task_card import TaskCardWidget, TaskStatus


@pytest.fixture
def main_window(qtbot):
    """메인 창 인스턴스를 생성하고 표시하는 fixture."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    return window


@pytest.mark.ticket("T0110")
def test_download_blocked_when_ffmpeg_unavailable(qtbot) -> None:
    """[T0110] FFmpeg가 사용 불가능할 때 다운로드가 차단되고 카드 상태가 유지되는지 검증."""
    mock_vod = VodInfo(
        video_no="12345",
        video_title="테스트 영상",
        channel_name="스트리머",
    )
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/12345",
        status=TaskStatus.READY,
        vod_info=mock_vod,
    )
    qtbot.addWidget(card)

    blocked_reasons: list[str] = []
    card.download_blocked.connect(blocked_reasons.append)

    # FFmpeg 미가용 상태 모킹
    with patch(
        "chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available", return_value=False
    ):
        started = card.trigger_start_download()
        assert started is False
        assert card.status == TaskStatus.READY  # DOWNLOADING 상태로 전이되지 않음
        assert len(blocked_reasons) == 1
        assert "FFmpeg를 사용할 수 없습니다" in blocked_reasons[0]


@pytest.mark.ticket("T0109")
def test_downloading_vod_rejects_duplicate_url(main_window, qtbot) -> None:
    """[T0109] VOD가 다운로드 중인 상태에서 동일 URL 입력 시 모달 없이 즉시 거부 토스트를 노출하는지 검증."""
    update_current_settings(vod_auto_download=True)
    mock_vod = VodInfo(
        video_no="15016450", video_title="진행 중 테스트", channel_name="스트리머A"
    )

    with patch("chzzk_downloader.gui.workers.extract_vod_info", return_value=mock_vod):
        test_url = "https://chzzk.naver.com/video/15016450"
        main_window.url_input.setText(test_url)
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

        card = main_window.task_list_widget.get_all_cards()[0]
        assert card.status == TaskStatus.DOWNLOADING

        # 다운로드 진행 중 동일 URL 재입력 -> 모달 호출 없이 즉시 거부 토스트
        with patch.object(main_window, "_confirm_redownload_dialog") as mock_confirm:
            main_window.url_input.setText(test_url)
            qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

            assert mock_confirm.called is False  # 모달 안 뜸
            assert main_window.url_input.text() == ""  # 입력창 비움
            assert main_window.toast.isHidden() is False
            assert "이미 추가한 작업입니다." in main_window.toast.label.text()
            assert main_window.task_list_widget.list_widget.count() == 1


@pytest.mark.ticket("T0109")
def test_analyzing_and_ready_vod_rejects_duplicate_url(main_window, qtbot) -> None:
    """[T0109] 읽는 중(ANALYZING) 및 대기 중(READY) 상태에서 동일 URL 재입력 시 모달 없이 즉시 거부 토스트 노출 검증."""
    test_url = "https://chzzk.naver.com/video/15016450"

    # 1. ANALYZING 상태 카드 생성
    card = TaskCardWidget(raw_url=test_url, status=TaskStatus.ANALYZING)
    main_window.task_list_widget.add_task_card(card)

    with patch.object(main_window, "_confirm_redownload_dialog") as mock_confirm:
        main_window.url_input.setText(test_url)
        main_window.download_btn.click()

        assert mock_confirm.called is False
        assert main_window.url_input.text() == ""
        assert main_window.toast.isHidden() is False
        assert "이미 추가한 작업입니다." in main_window.toast.label.text()
        assert main_window.task_list_widget.list_widget.count() == 1

    # 2. READY 상태로 전이 후 재입력 시도
    card.status = TaskStatus.READY
    card._update_display()
    main_window.toast.hide()

    with patch.object(main_window, "_confirm_redownload_dialog") as mock_confirm:
        main_window.url_input.setText(test_url)
        main_window.download_btn.click()

        assert mock_confirm.called is False
        assert main_window.url_input.text() == ""
        assert main_window.toast.isHidden() is False
        assert "이미 추가한 작업입니다." in main_window.toast.label.text()
        assert main_window.task_list_widget.list_widget.count() == 1


@pytest.mark.ticket("T0109")
def test_rapid_successive_same_url_inputs_blocked(main_window, qtbot) -> None:
    """[T0109] 동일 URL이 아주 짧은 시간 간격으로 연속 입력되었을 때 중복 생성을 즉시 차단하는지 검증."""
    mock_vod = VodInfo(
        video_no="15016450", video_title="연속 입력 테스트", channel_name="스트리머A"
    )

    with patch("chzzk_downloader.gui.workers.extract_vod_info", return_value=mock_vod):
        test_url = "https://chzzk.naver.com/video/15016450"

        # 1. 첫 번째 입력 실행
        main_window.url_input.setText(test_url)
        main_window._on_download_clicked()

        # 작업 목록에 즉시 분석 중(ANALYZING) 카드가 등록되고 입력창 비움
        assert main_window.url_input.text() == ""
        assert main_window.task_list_widget.list_widget.count() == 1
        card = main_window.task_list_widget.get_all_cards()[0]
        assert card.status == TaskStatus.ANALYZING

        # 2. 아주 짧은 시간 간격으로 동일 URL을 3회 연속 빠르게 입력 시도 (ANALYZING 도중 연타)
        for _ in range(3):
            main_window.url_input.setText(test_url)
            main_window._on_download_clicked()

            # 입력칸은 즉시 비워짐
            assert main_window.url_input.text() == ""
            # 카드 개수는 1개로 엄격히 유지 (중복 생성 원천 차단)
            assert main_window.task_list_widget.list_widget.count() == 1
            # 거부 토스트 출력 확인
            assert main_window.toast.isHidden() is False
            assert "이미 추가한 작업입니다." in main_window.toast.label.text()

        # 3. 비동기 VOD 분석 완료 후(DOWNLOADING)에도 동일 URL 입력 차단 검증
        qtbot.waitUntil(lambda: card.status == TaskStatus.DOWNLOADING, timeout=5000)
        assert card.status == TaskStatus.DOWNLOADING

        main_window.url_input.setText(test_url)
        main_window._on_download_clicked()

        assert main_window.url_input.text() == ""
        assert main_window.task_list_widget.list_widget.count() == 1
        assert main_window.toast.isHidden() is False
        assert "이미 추가한 작업입니다." in main_window.toast.label.text()


@pytest.mark.ticket("T0105")
def test_reproduce_and_defend_deleted_card_during_worker_analysis(
    main_window, qtbot
) -> None:
    """[T0105] Merge Blocker 버그 방어: 분석 중 카드를 삭제했을 때 늦게 도착한 worker 응답으로 인한 크래시 방지 검증."""
    mock_vod = VodInfo(
        video_no="15016450",
        video_title="치지직 테스트 영상",
        channel_name="스트리머A",
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
        test_url = "https://chzzk.naver.com/video/15016450"
        main_window.url_input.setText(test_url)
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

        # 1. 분석 중 카드 생성 확인
        assert main_window.task_list_widget.list_widget.count() == 1
        card = main_window.task_list_widget.get_all_cards()[0]
        assert card.status == TaskStatus.ANALYZING

        # 2. worker가 끝나기 전에 사용자가 카드의 삭제 버튼(✕) 클릭
        card.delete_btn.click()
        QApplication.processEvents()

        # 3. 카드가 목록에서 즉시 제거되었는지 확인
        assert main_window.task_list_widget.list_widget.count() == 0
        assert (
            main_window.task_list_widget.stack.currentWidget()
            == main_window.task_list_widget.empty_label
        )

        # 4. worker가 지연 후 종료될 때까지 대기
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

        # 5. 기대 결과: RuntimeError 없이 앱 정상 생존, 카드가 부활하지 않음
        assert main_window.task_list_widget.list_widget.count() == 0


@pytest.mark.ticket("T0105")
def test_reproduce_and_defend_deleted_card_during_worker_failure(
    main_window, qtbot
) -> None:
    """[T0105] 분석 중 카드를 삭제했을 때 실패(401 등) 결과가 늦게 도착해도 크래시 없이 무시되는지 검증."""

    def slow_fail(_url):
        time.sleep(0.3)
        raise YtDlpError("HTTP Error 401: Unauthorized")

    with patch("chzzk_downloader.gui.workers.extract_vod_info", side_effect=slow_fail):
        test_url = "https://chzzk.naver.com/video/15021267"
        main_window.url_input.setText(test_url)
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

        assert main_window.task_list_widget.list_widget.count() == 1
        card = main_window.task_list_widget.get_all_cards()[0]

        # 분석 도중 삭제
        card.delete_btn.click()
        QApplication.processEvents()
        assert main_window.task_list_widget.list_widget.count() == 0

        # worker 완료 대기
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

        # 크래시 없이 작업 없음 상태 유지
        assert main_window.task_list_widget.list_widget.count() == 0


@pytest.mark.ticket("T0105")
def test_reproduce_and_defend_deleted_card_thumbnail_loaded(qtbot) -> None:
    """[T0105] 썸네일 다운로드 중 카드가 삭제되었을 때 _on_thumbnail_loaded 호출로 인한 크래시 방지 검증."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/123",
        status=TaskStatus.READY,
    )
    qtbot.addWidget(card)

    # 카드를 삭제 상태로 전이
    card.deleteLater()
    QApplication.processEvents()

    # 늦게 도착한 썸네일 바이트 처리 시도시 예외 없이 무시되어야 함
    card._on_thumbnail_loaded(b"dummy_bytes")


@pytest.mark.ticket("T0105")
def test_duplicate_valid_vod_url_blocked(main_window, qtbot) -> None:
    """[T0105] 동일한 치지직 VOD URL 중복 입력 시 재다운로드 모달에서 취소하면 카드 생성을 차단하는지 검증."""
    mock_vod = VodInfo(
        video_no="15016450",
        video_title="중복 테스트 방송",
        channel_name="스트리머B",
        duration=1800,
        formats=[VodFormatInfo(format_id="720p", height=720, fps=30.0)],
        live_open_date="2024-05-06",
    )

    with patch("chzzk_downloader.gui.workers.extract_vod_info", return_value=mock_vod):
        test_url = "https://chzzk.naver.com/video/15016450"

        # 1. 첫 번째 입력 -> 정상 추가
        main_window.url_input.setText(test_url)
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

        assert main_window.task_list_widget.list_widget.count() == 1

        # 2. 동일한 VOD URL 두 번째 입력 (카드가 DOWNLOADING 상태이므로 즉시 거부 토스트 노출)
        main_window.url_input.setText(f"  {test_url}  ")
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

        # 입력칸은 즉시 비워짐
        assert main_window.url_input.text() == ""

        # 목록 카드 개수는 여전히 1개로 유지 (중복 생성 차단)
        assert main_window.task_list_widget.list_widget.count() == 1

        # 중복 안내 토스트 노출 및 2초 자동 소멸 확인
        assert main_window.toast.isHidden() is False
        assert "이미 추가한 작업입니다." in main_window.toast.label.text()
        assert main_window.toast._timer.isActive() is True
        assert main_window.toast._timer.interval() == SUCCESS_TOAST_DURATION_MS


@pytest.mark.ticket("T0105")
def test_duplicate_invalid_url_blocked(main_window, qtbot) -> None:
    """[T0105] 동일한 유효하지 않은 URL 중복 입력 시에도 확인 모달 취소 시 카드 중복 생성을 차단하는지 검증."""
    invalid_url = "https://example.com/not-a-vod"

    # 1. 첫 번째 입력 -> Invalid 카드 추가
    main_window.url_input.setText(invalid_url)
    qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

    assert main_window.task_list_widget.list_widget.count() == 1

    # 2. 동일한 잘못된 URL 재입력 -> 확인 모달 취소 시 중복 차단
    with patch.object(
        main_window, "_confirm_redownload_dialog", return_value=False
    ) as mock_confirm:
        main_window.url_input.setText(invalid_url)
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

        assert mock_confirm.called is True
        assert main_window.url_input.text() == ""
        assert main_window.task_list_widget.list_widget.count() == 1


@pytest.mark.ticket("T0105")
def test_deleted_card_can_be_readded_after_deletion(main_window, qtbot) -> None:
    """[T0105] 카드를 삭제한 이후에는 동일한 URL을 다시 추가할 수 있는지 검증."""
    mock_vod = VodInfo(
        video_no="15016450",
        video_title="재등록 테스트",
        channel_name="스트리머C",
        duration=1200,
    )

    with patch("chzzk_downloader.gui.workers.extract_vod_info", return_value=mock_vod):
        test_url = "https://chzzk.naver.com/video/15016450"

        # 1. 추가 후 완료
        main_window.url_input.setText(test_url)
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)
        assert main_window.task_list_widget.list_widget.count() == 1

        # 2. 카드 삭제
        card = main_window.task_list_widget.get_all_cards()[0]
        card.delete_btn.click()
        QApplication.processEvents()
        assert main_window.task_list_widget.list_widget.count() == 0

        # 3. 삭제 후 동일 URL 재입력 -> 정상 등록되어야 함
        main_window.url_input.setText(test_url)
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

        assert main_window.task_list_widget.list_widget.count() == 1
        readded_card = main_window.task_list_widget.get_all_cards()[0]
        assert readded_card.status in (TaskStatus.READY, TaskStatus.DOWNLOADING)
