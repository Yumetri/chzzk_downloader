"""작업 카드(TaskCard) 다운로드 시작, 기본 화질/확장자 반영 및 파일명 중복 대화상자(덮어쓰기/이름변경/취소) 분기 GUI 테스트."""

from pathlib import Path
from unittest.mock import patch

import pytest

from chzzk_downloader.core.filename_generator import generate_vod_filename
from chzzk_downloader.core.settings_manager import update_current_settings
from chzzk_downloader.core.ytdlp import VodFormatInfo, VodInfo
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.task_card import TaskCardWidget, TaskStatus


@pytest.fixture
def main_window(qtbot):
    """메인 창 인스턴스를 생성하고 표시하는 fixture."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    return window


@pytest.mark.ticket("T0109")
def test_start_download_and_file_duplicate_handling(qtbot, tmp_path: Path) -> None:
    """[T0109] 파일 중복 시 덮어쓰기 / 이름변경 / 취소 분기 및 UI 상태 전이 검증."""
    save_dir = tmp_path / "downloads"
    save_dir.mkdir()
    update_current_settings(download_dir=str(save_dir), vod_auto_download=False)

    mock_vod = VodInfo(
        video_no="15016450",
        video_title="테스트 영상",
        channel_name="스트리머A",
        duration=1800,
    )
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15016450",
        status=TaskStatus.READY,
        vod_info=mock_vod,
    )
    qtbot.addWidget(card)

    expected_file = save_dir / generate_vod_filename(mock_vod, ext=".mp4")

    # 1. 파일이 없을 때 -> 즉시 DOWNLOADING 전이
    assert expected_file.exists() is False
    card.trigger_start_download()
    assert card.status == TaskStatus.DOWNLOADING
    assert card.target_path == expected_file
    assert card.ready_container.isHidden() is True
    assert card.downloading_container.isHidden() is False
    assert card.recording_label.text() == "녹화 중…"
    assert card.spinner._timer.isActive() is True

    # 2. 동일 파일 생성
    expected_file.touch()
    card.status = TaskStatus.READY
    card._update_display()

    # 2-1. 중복 파일 존재 시: '취소' 선택
    with patch.object(card, "_prompt_duplicate_resolution", return_value="cancel"):
        ok = card.trigger_start_download()
        assert ok is False
        assert card.status == TaskStatus.READY

    # 2-2. 중복 파일 존재 시: '이름 변경' 선택
    with patch.object(card, "_prompt_duplicate_resolution", return_value="rename"):
        ok = card.trigger_start_download()
        assert ok is True
        assert card.status == TaskStatus.DOWNLOADING
        assert card.target_path is not None
        assert card.target_path.name == f"{expected_file.stem} (1).mp4"

    # 2-3. 중복 파일 존재 시: '덮어쓰기' 선택
    card.status = TaskStatus.READY
    card._update_display()
    with patch.object(card, "_prompt_duplicate_resolution", return_value="overwrite"):
        ok = card.trigger_start_download()
        assert ok is True
        assert card.status == TaskStatus.DOWNLOADING
        assert card.target_path == expected_file


@pytest.mark.ticket("T0109")
def test_vod_auto_download_off_prioritizes_settings_default_quality_and_extension(
    main_window, qtbot
) -> None:
    """[T0109] 자동 다운로드 OFF 시 4번 위치에 설정의 기본 화질/확장자가 우선 선택되고 3번 위치에 표시되는지 검증."""
    update_current_settings(
        vod_auto_download=False,
        default_quality="720p",
        file_extension=".ts",
    )

    mock_vod = VodInfo(
        video_no="15016450",
        video_title="기본 설정 테스트 방송",
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
        main_window.download_btn.click()
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

        card = main_window.task_list_widget.get_all_cards()[0]

        # 1. 3번 위치(우하단)에 설정의 기본 화질(720p) 및 재생시간 표시
        assert card.status_label.text() == "720p | 01:00:00"

        # 2. 4번 위치의 화질 드롭다운에 '720p'가 우선 선택되어 나타남
        assert card.quality_combo.currentText() == "720p"

        # 3. 4번 위치의 확장자 드롭다운에 '.ts'가 기본 선택되어 나타남
        assert card.ext_combo.currentText() == ".ts"

        # 4. 클릭 시 드롭다운 항목에는 가능한 모든 화질 목록이 제공됨
        combo_items = [
            card.quality_combo.itemText(i) for i in range(card.quality_combo.count())
        ]
        assert combo_items == ["1080p60", "720p", "480p"]

        # 5. 사용자가 4번 위치에서 화질을 '480p'로 변경 시 3번 위치의 화질 표시도 실시간 갱신
        card.quality_combo.setCurrentText("480p")
        assert card.selected_quality == "480p"
        assert card.status_label.text() == "480p | 01:00:00"
