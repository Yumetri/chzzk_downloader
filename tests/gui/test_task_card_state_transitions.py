"""작업 카드 상태 전이(ANALYZING -> READY -> DOWNLOADING -> STOPPED) 및 재다운로드 클린 리셋 GUI 테스트."""

from unittest.mock import patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from chzzk_downloader.core.settings_manager import update_current_settings
from chzzk_downloader.core.ytdlp import VodFormatInfo, VodInfo
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.task_card import TaskCardWidget, TaskStatus


@pytest.fixture
def main_window(qtbot):
    """메인 창 fixture."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    return window


@pytest.mark.ticket("T0109")
def test_task_card_title_reading_url(qtbot) -> None:
    """[T0109] 분석 중 카드 생성 시 1번 위치 문구가 '읽는 중… {URL}'로 표시되는지 검증."""
    test_url = "https://chzzk.naver.com/video/15016450"
    card = TaskCardWidget(raw_url=test_url, status=TaskStatus.ANALYZING)
    qtbot.addWidget(card)

    assert card.title_label.text() == f"읽는 중… {test_url}"


@pytest.mark.ticket("T0109")
def test_vod_auto_download_off_shows_waiting_controls(main_window, qtbot) -> None:
    """[T0109] VOD 자동 다운로드가 OFF일 때 분석 완료 후 READY 상태 유지 및 4번 위치 대기 컨트롤 노출 검증."""
    update_current_settings(vod_auto_download=False)

    mock_vod = VodInfo(
        video_no="15016450",
        video_title="대기 테스트 방송",
        channel_name="스트리머A",
        duration=3600,
        formats=[
            VodFormatInfo(format_id="1080p", height=1080, fps=60.0),
            VodFormatInfo(format_id="720p", height=720, fps=30.0),
            VodFormatInfo(format_id="480p", height=480, fps=30.0),
        ],
        live_open_date="2024-05-06",
    )

    with patch("chzzk_downloader.gui.workers.extract_vod_info", return_value=mock_vod):
        test_url = "https://chzzk.naver.com/video/15016450"
        main_window.url_input.setText(test_url)
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

        card = main_window.task_list_widget.get_all_cards()[0]

        assert card.status == TaskStatus.READY
        assert card.ready_container.isHidden() is False
        assert card.downloading_container.isHidden() is True
        assert card.quality_combo.currentText() == "1080p60"
        assert card.ext_combo.currentText() == ".mp4"
        assert card.folder_btn.isHidden() is False
        assert card.start_btn.isHidden() is False


@pytest.mark.ticket("T0109")
def test_stop_download_confirmation(qtbot) -> None:
    """[T0109] 중지 버튼 클릭 시 모달 승인 시 STOPPED 완결 상태 전이 및 4번 위치 비노출 검증."""
    mock_vod = VodInfo(
        video_no="15016450", video_title="중지 테스트", channel_name="스트리머A"
    )
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15016450",
        status=TaskStatus.DOWNLOADING,
        vod_info=mock_vod,
    )
    qtbot.addWidget(card)

    # 아니오(No) 선택 -> 다운로드 유지
    with patch(
        "PyQt6.QtWidgets.QMessageBox.question",
        return_value=QMessageBox.StandardButton.No,
    ):
        card.stop_btn.click()
        assert card.status == TaskStatus.DOWNLOADING

    # 예(Yes) 선택 -> STOPPED 완결 상태 전이 및 4번 위치 숨김
    with patch(
        "PyQt6.QtWidgets.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        card.stop_btn.click()
        assert card.status == TaskStatus.STOPPED
        assert card.ready_container.isHidden() is True
        assert card.downloading_container.isHidden() is True


@pytest.mark.ticket("T0109")
def test_redownload_stopped_vod_clean_reset(main_window, qtbot) -> None:
    """[T0109] 중지된 VOD 카드가 남아있는 상태에서 동일 URL 재입력 시 확인 모달 및 클린 리셋 검증."""
    update_current_settings(vod_auto_download=True)
    mock_vod = VodInfo(
        video_no="15016450", video_title="재다운로드 테스트", channel_name="스트리머A"
    )

    with patch("chzzk_downloader.gui.workers.extract_vod_info", return_value=mock_vod):
        test_url = "https://chzzk.naver.com/video/15016450"
        main_window.url_input.setText(test_url)
        qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

        card = main_window.task_list_widget.get_all_cards()[0]
        card.status = TaskStatus.STOPPED
        card._update_display()

        # 취소 선택 시 -> 카드 유지, 입력창 비움
        with patch.object(
            main_window, "_confirm_redownload_dialog", return_value=False
        ):
            main_window.url_input.setText(test_url)
            qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

            assert main_window.url_input.text() == ""
            assert main_window.task_list_widget.list_widget.count() == 1
            assert card.status == TaskStatus.STOPPED

        # 확인 선택 시 -> 클린 리셋 후 재분석/재다운로드 정상 진행
        with patch.object(main_window, "_confirm_redownload_dialog", return_value=True):
            with patch.object(
                card, "reset_for_redownload", wraps=card.reset_for_redownload
            ) as mock_reset:
                main_window.url_input.setText(test_url)
                qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)
                assert mock_reset.called is True

                qtbot.waitUntil(
                    lambda: main_window.download_btn.isEnabled(), timeout=2000
                )
                assert main_window.task_list_widget.list_widget.count() == 1
                assert card.status in (TaskStatus.READY, TaskStatus.DOWNLOADING)


@pytest.mark.ticket("T0109")
def test_vod_auto_download_on_downloads_with_settings_default_quality_and_extension(
    main_window, qtbot
) -> None:
    """[T0109] VOD 자동 다운로드 ON 시 설정의 기본 화질 및 확장자로 즉시 다운로드가 자동 시작되는지 검증."""
    update_current_settings(
        vod_auto_download=True,
        default_quality="720p",
        file_extension=".ts",
    )

    mock_vod = VodInfo(
        video_no="15016450",
        video_title="자동 다운로드 화질 테스트",
        channel_name="스트리머A",
        duration=1800,
        formats=[
            VodFormatInfo(format_id="1080p", height=1080, fps=60.0),
            VodFormatInfo(format_id="720p", height=720, fps=30.0),
            VodFormatInfo(format_id="480p", height=480, fps=30.0),
        ],
    )

    with patch("chzzk_downloader.gui.workers.extract_vod_info", return_value=mock_vod):
        test_url = "https://chzzk.naver.com/video/15016450"
        main_window.url_input.setText(test_url)
        main_window.download_btn.click()
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

        card = main_window.task_list_widget.get_all_cards()[0]

        assert card.status == TaskStatus.DOWNLOADING
        assert "720p" in card.status_label.text()
        assert card.selected_quality == "720p"
        assert card.target_path is not None
        assert card.target_path.suffix == ".ts"


@pytest.mark.ticket("T0109")
def test_stopped_vod_redownload_applies_new_settings_quality_and_extension(
    main_window, qtbot
) -> None:
    """[T0109] URL 입력 -> 설정에서 기본화질/확장자 변경 -> 작업 중단 -> 동일 URL 재시작 시 최신 설정을 따르는지 검증."""
    update_current_settings(
        vod_auto_download=False,
        default_quality="1080p",
        file_extension=".mp4",
    )

    mock_vod = VodInfo(
        video_no="15016450",
        video_title="재시작 설정 변경 테스트",
        channel_name="스트리머A",
        duration=3600,
        formats=[
            VodFormatInfo(format_id="1080p", height=1080, fps=60.0),
            VodFormatInfo(format_id="720p", height=720, fps=30.0),
            VodFormatInfo(format_id="480p", height=480, fps=30.0),
        ],
    )

    with patch("chzzk_downloader.gui.workers.extract_vod_info", return_value=mock_vod):
        test_url = "https://chzzk.naver.com/video/15016450"
        main_window.url_input.setText(test_url)
        main_window.download_btn.click()
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

        card = main_window.task_list_widget.get_all_cards()[0]
        assert card.quality_combo.currentText() == "1080p60"
        assert card.ext_combo.currentText() == ".mp4"

        # 다운로드 시작 후 즉시 중단
        card.trigger_start_download()
        assert card.status == TaskStatus.DOWNLOADING
        with patch.object(card, "_confirm_stop_dialog", return_value=True):
            card.trigger_stop_download()
        assert card.status == TaskStatus.STOPPED

        # 설정 변경
        update_current_settings(
            default_quality="720p",
            file_extension=".ts",
        )

        # 동일 URL 재다운로드
        with patch.object(main_window, "_confirm_redownload_dialog", return_value=True):
            main_window.url_input.setText(test_url)
            main_window.download_btn.click()
            qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

            card_after = main_window.task_list_widget.get_all_cards()[0]
            assert card_after.quality_combo.currentText() == "720p"
            assert card_after.ext_combo.currentText() == ".ts"
