"""T0105. VOD 분석 진행·취소·오류 및 중복 방지 (Merge Blocker & 중복 방지) 단위/통합 테스트."""

import time
from unittest.mock import patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from chzzk_downloader.config import SUCCESS_TOAST_DURATION_MS
from chzzk_downloader.core.ytdlp import (
    VodFormatInfo,
    VodInfo,
    YtDlpError,
)
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.task_card import TaskCardWidget, TaskStatus


@pytest.fixture
def main_window(qtbot):
    """메인 창 인스턴스를 생성하고 표시하는 fixture."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    return window


def test_reproduce_and_defend_deleted_card_during_worker_analysis(main_window, qtbot):
    """Merge Blocker 버그 재현 및 방어: 분석 중 카드를 삭제했을 때 늦게 도착한 worker 응답으로 인한 크래시 방지 검증."""
    mock_vod = VodInfo(
        video_no="15016450",
        video_title="치지직 테스트 영상",
        channel_name="스트리머A",
        duration=3600,
        formats=[VodFormatInfo(format_id="1080p", height=1080, fps=60.0)],
        live_open_date="2024-05-06",
    )

    def slow_extract(_url):
        # 0.3초 지연을 주어 분석 진행 중 카드 삭제가 일어나도록 유도
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

        # 5. 기대 결과:
        # - RuntimeError(wrapped C/C++ object has been deleted) 없이 앱이 정상 생존
        # - 삭제된 카드가 목록에 다시 나타나지 않음
        assert main_window.task_list_widget.list_widget.count() == 0


def test_reproduce_and_defend_deleted_card_during_worker_failure(main_window, qtbot):
    """분석 중 카드를 삭제했을 때 실패(401 등) 결과가 늦게 도착해도 크래시 없이 무시되는지 검증."""

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


def test_reproduce_and_defend_deleted_card_thumbnail_loaded(qtbot):
    """썸네일 다운로드 중 카드가 삭제되었을 때 _on_thumbnail_loaded 호출로 인한 크래시 방지 검증."""
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


def test_duplicate_valid_vod_url_blocked(main_window, qtbot):
    """동일한 치지직 VOD URL 중복 입력 시 재다운로드 모달에서 취소하면 카드 생성을 차단하는지 검증."""
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


def test_duplicate_invalid_url_blocked(main_window, qtbot):
    """동일한 유효하지 않은 URL 중복 입력 시에도 확인 모달 취소 시 카드 중복 생성을 차단하는지 검증."""
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


def test_deleted_card_can_be_readded_after_deletion(main_window, qtbot):
    """카드를 삭제한 이후에는 동일한 URL을 다시 추가할 수 있는지 검증."""
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
