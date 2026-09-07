"""T0109. VOD 다운로드 설정 및 진입 제어 단위/통합 테스트."""

from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from chzzk_downloader.core.filename_generator import (
    generate_vod_filename,
    resolve_duplicate_filename,
    sanitize_filename,
)
from chzzk_downloader.core.settings_manager import (
    get_current_settings,
    update_current_settings,
)
from chzzk_downloader.core.ytdlp import VodFormatInfo, VodInfo
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.settings_window import SettingsWindow
from chzzk_downloader.gui.switch_widget import SwitchWidget
from chzzk_downloader.gui.task_card import TaskCardWidget, TaskStatus


@pytest.fixture
def temp_settings_env(tmp_path):
    """임시 디렉터리에 격리된 settings.json 환경을 제공하는 fixture."""
    from chzzk_downloader.core.settings_manager import set_custom_settings_path

    test_settings_dir = tmp_path / ".chzzk_downloader"
    test_settings_file = test_settings_dir / "settings.json"
    set_custom_settings_path(test_settings_file)

    update_current_settings(
        download_dir=str(tmp_path / "chzzk_downloaded"),
        default_quality="최고 화질",
        file_extension=".mp4",
        vod_auto_download=True,
    )
    yield test_settings_file
    set_custom_settings_path(None)


@pytest.fixture
def main_window(qtbot, temp_settings_env):
    """메인 창 fixture."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    return window


# 1. 파일명 생성 및 중복 해결 단위 테스트
def test_sanitize_filename_converts_colon():
    """콜론을 전각 콜론으로 치환하고 금지 문자를 정제하는지 검증."""
    raw = '방송: 다시보기? <1> / 테스트 * | "호환"'
    sanitized = sanitize_filename(raw)
    assert ":" not in sanitized
    assert "：" in sanitized  # 전각 콜론
    assert "?" not in sanitized
    assert "<" not in sanitized
    assert ">" not in sanitized
    assert "/" not in sanitized
    assert "*" not in sanitized
    assert "|" not in sanitized
    assert '"' not in sanitized


def test_generate_vod_filename_with_and_without_live_date():
    """live_open_date 유무에 따른 파일명 명명 규칙 검증."""
    info_with_date = VodInfo(
        video_no="12345",
        video_title="테스트: 라이브",
        channel_name="스트리머A",
        live_open_date="2024-05-06",
    )
    name1 = generate_vod_filename(info_with_date, ext=".mp4")
    assert "date：2024-05-06" in name1
    assert "스트리머A" in name1

    info_without_date = VodInfo(
        video_no="67890",
        video_title="일반 영상",
        channel_name="스트리머B",
        live_open_date="",
    )
    name2 = generate_vod_filename(info_without_date, ext=".ts")
    assert name2 == "[스트리머B] 일반 영상 (67890).ts"


def test_resolve_duplicate_filename(tmp_path):
    """동일 파일이 존재할 경우 (1), (2) 넘버링된 고유 경로 반환 검증."""
    base_file = tmp_path / "video.mp4"
    base_file.touch()

    res1 = resolve_duplicate_filename(base_file)
    assert res1.name == "video (1).mp4"

    res1.touch()
    res2 = resolve_duplicate_filename(base_file)
    assert res2.name == "video (2).mp4"


# 2. 토글 스위치 위젯 단위 테스트
def test_switch_widget_toggle(qtbot):
    """SwitchWidget 클릭 시 상태 전환 및 toggled 시그널 방출 검증."""
    switch = SwitchWidget(checked=True)
    qtbot.addWidget(switch)
    assert switch.isChecked() is True

    signal_received = []
    switch.toggled.connect(lambda v: signal_received.append(v))

    qtbot.mouseClick(switch, Qt.MouseButton.LeftButton)
    assert switch.isChecked() is False
    assert signal_received == [False]

    switch.setChecked(True)
    assert switch.isChecked() is True
    assert signal_received == [False, True]


# 3. SettingsWindow 토글 스위치 및 영속화 검증
def test_settings_window_vod_auto_download_toggle(qtbot, temp_settings_env):
    """SettingsWindow에서 VOD 자동 다운로드 스위치 조작 시 settings.json에 영속화되는지 검증."""
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()

    assert window.auto_switch.isChecked() is True
    assert get_current_settings().vod_auto_download is True

    qtbot.mouseClick(window.auto_switch, Qt.MouseButton.LeftButton)
    assert window.auto_switch.isChecked() is False
    assert get_current_settings().vod_auto_download is False

    # 새 인스턴스로 다시 로드 시 저장된 값 복원 검증
    window2 = SettingsWindow()
    qtbot.addWidget(window2)
    assert window2.auto_switch.isChecked() is False


# 4. 카드 1번 위치 문구 검증: 읽는 중… URL
def test_task_card_title_reading_url(qtbot):
    """분석 중 카드 생성 시 1번 위치 문구가 '읽는 중… {URL}'로 표시되는지 검증."""
    test_url = "https://chzzk.naver.com/video/15016450"
    card = TaskCardWidget(raw_url=test_url, status=TaskStatus.ANALYZING)
    qtbot.addWidget(card)

    assert card.title_label.text() == f"읽는 중… {test_url}"


# 5. VOD 자동 다운로드 OFF 시 4번 위치 대기 컨트롤 및 개별 설정(화질 드롭다운, 확장자 드롭다운, 폴더) 검증
def test_vod_auto_download_off_shows_waiting_controls(main_window, qtbot):
    """VOD 자동 다운로드가 OFF일 때 분석 완료 후 READY 상태 유지 및 4번 위치 대기 컨트롤(화질/확장자 콤보) 노출 검증."""
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

        # 1. 카드는 READY 상태로 유지됨
        assert card.status == TaskStatus.READY

        # 2. 4번 위치 대기 컨테이너 노출 및 화질/확장자/폴더/시작 버튼 확인
        assert card.ready_container.isHidden() is False
        assert card.downloading_container.isHidden() is True
        assert card.quality_combo.currentText() == "1080p60"  # 최고화질 기본 선택
        assert card.ext_combo.currentText() == ".mp4"  # 확장자 드롭다운 기본값
        assert card.folder_btn.isHidden() is False
        assert card.start_btn.isHidden() is False

        # 3. 화질 변경 테스트
        card.quality_combo.setCurrentText("720p")
        assert card.selected_quality == "720p"

        # 4. 확장자 드롭다운 변경 테스트 (.ts 선택)
        card.ext_combo.setCurrentText(".ts")
        assert card.ext_combo.currentText() == ".ts"

        # 5. 폴더 변경 테스트 (QFileDialog 모킹)
        custom_folder = "C:/custom/download/path"
        with patch(
            "PyQt6.QtWidgets.QFileDialog.getExistingDirectory",
            return_value=custom_folder,
        ):
            card.folder_btn.click()
            assert card.custom_download_dir == Path(custom_folder).resolve()


# 6. 시작 아이콘(▶) 클릭 시 다운로드 시작 및 파일 중복 처리(옵션 A) 검증
def test_start_download_and_file_duplicate_handling(qtbot, tmp_path):
    """파일 중복 시 덮어쓰기 / 이름변경 / 취소 분기 및 UI 상태 전이 검증."""
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


# 7. 다운로드 중지 버튼(■) 및 완결(STOPPED) 상태 전이 검증
def test_stop_download_confirmation(qtbot, tmp_path):
    """중지 버튼 클릭 시 모달 승인 시 STOPPED 완결 상태 전이 및 4번 위치 비노출 검증."""
    mock_vod = VodInfo(
        video_no="15016450", video_title="중지 테스트", channel_name="스트리머A"
    )
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15016450",
        status=TaskStatus.DOWNLOADING,
        vod_info=mock_vod,
    )
    qtbot.addWidget(card)

    # 1. 중지 확인 모달에서 '아니오(No)' 선택 -> 다운로드 유지
    with patch(
        "PyQt6.QtWidgets.QMessageBox.question",
        return_value=QMessageBox.StandardButton.No,
    ):
        card.stop_btn.click()
        assert card.status == TaskStatus.DOWNLOADING

    # 2. 중지 확인 모달에서 '예(Yes)' 선택 -> STOPPED 완결 상태 전이 및 4번 위치 숨김
    with patch(
        "PyQt6.QtWidgets.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        card.stop_btn.click()
        assert card.status == TaskStatus.STOPPED
        # 중지 후 재개 불가 완결 작업이므로 4번 위치의 모든 컨트롤 숨김
        assert card.ready_container.isHidden() is True
        assert card.downloading_container.isHidden() is True
        assert card.spinner._timer.isActive() is False
        assert "중지됨" in card.status_label.text()


# 8. VOD가 다운로드 중인 상태에서 동일 URL 재입력 시 즉시 거부 검증
def test_downloading_vod_rejects_duplicate_url(main_window, qtbot):
    """VOD가 다운로드 중인 상태에서 동일 URL 입력 시 모달 없이 즉시 거부 토스트를 노출하는지 검증."""
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


# 9. 중지(STOPPED) 상태에서 동일 VOD 재입력 시 확인 모달 및 클린 리셋 무결성 검증
def test_redownload_stopped_vod_clean_reset(main_window, qtbot):
    """중지된 VOD 카드가 남아있는 상태에서 동일 URL 재입력 시 확인 모달 및 클린 리셋 검증."""
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
        # 다운로드를 중지시켜 STOPPED 상태로 만듦
        card.status = TaskStatus.STOPPED
        card._update_display()

        # 1. 취소 선택 시 -> 카드 유지, 입력창 비움, 추가 동작 없음
        with patch.object(
            main_window, "_confirm_redownload_dialog", return_value=False
        ):
            main_window.url_input.setText(test_url)
            qtbot.mouseClick(main_window.download_btn, Qt.MouseButton.LeftButton)

            assert main_window.url_input.text() == ""
            assert main_window.task_list_widget.list_widget.count() == 1
            assert card.status == TaskStatus.STOPPED

        # 2. 확인 선택 시 -> 클린 리셋 후 재분석/재다운로드 정상 진행
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
                # 재다운로드 완료 후 목록 개수 1개 유지 및 정상 상태 확인
                assert main_window.task_list_widget.list_widget.count() == 1
                assert card.status in (TaskStatus.READY, TaskStatus.DOWNLOADING)


# 10. 읽는 중(ANALYZING) 및 대기 중(READY) 상태에서 동일 URL 재입력 시 즉시 거부 검증
def test_analyzing_and_ready_vod_rejects_duplicate_url(main_window, qtbot):
    """읽는 중(ANALYZING) 및 대기 중(READY) 상태에서 동일 URL 재입력 시 모달 없이 즉시 거부 토스트 노출 검증."""
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


# 11. 동일 URL이 아주 짧은 시간 간격으로 연속 입력(연타)되었을 때 중복 생성 즉시 차단 검증
def test_rapid_successive_same_url_inputs_blocked(main_window, qtbot):
    """동일 URL이 아주 짧은 시간 간격으로 연속 입력되었을 때 중복 생성을 즉시 차단하는지 검증."""
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
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)
        assert card.status == TaskStatus.DOWNLOADING

        main_window.url_input.setText(test_url)
        main_window._on_download_clicked()

        assert main_window.url_input.text() == ""
        assert main_window.task_list_widget.list_widget.count() == 1
        assert main_window.toast.isHidden() is False
        assert "이미 추가한 작업입니다." in main_window.toast.label.text()


# 12. 화질 매칭 도우미 함수 단위 검증
def test_match_default_quality_helper():
    """설정의 기본 화질에 따라 제공 화질 목록에서 가장 적합한 화질이 매칭되는지 검증."""
    from chzzk_downloader.gui.task_card import match_default_quality

    qualities = ["1080p60", "720p", "480p"]
    assert match_default_quality(qualities, "최고 화질") == "1080p60"
    assert match_default_quality(qualities, "1080p") == "1080p60"
    assert match_default_quality(qualities, "720p") == "720p"
    assert match_default_quality(qualities, "480p") == "480p"

    # 설정한 화질이 목록에 없을 때 (예: 720p 설정인데 480p, 360p만 있는 경우) -> 이하 중 최고 화질
    lower_qualities = ["480p", "360p"]
    assert match_default_quality(lower_qualities, "720p") == "480p"


# 13. VOD 자동 다운로드 OFF 시: 설정의 기본 화질/확장자 우선 선택 및 3번 위치 표시 검증
def test_vod_auto_download_off_prioritizes_settings_default_quality_and_extension(
    main_window, qtbot
):
    """자동 다운로드 OFF 시 4번 위치에 설정의 기본 화질/확장자가 우선 선택되고 3번 위치에 표시되는지 검증."""
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


# 14. VOD 자동 다운로드 ON 시: 설정의 기본 화질로 3번 위치에 표시되고 해당 화질/확장자로 다운로드 시작 검증
def test_vod_auto_download_on_downloads_with_settings_default_quality_and_extension(
    main_window, qtbot
):
    """자동 다운로드 ON 시 3번 위치에 설정 화질이 표시되고 지정된 화질/확장자로 다운로드 시작되는지 검증."""
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

        # 1. DOWNLOADING 상태로 자동 진입
        assert card.status == TaskStatus.DOWNLOADING

        # 2. 3번 위치에 설정의 기본 화질(720p) 표시
        assert "720p" in card.status_label.text()

        # 3. 선택된 화질이 720p로 확정되어 다운로드됨
        assert card.selected_quality == "720p"

        # 4. 다운로드 파일명이 설정의 기본 확장자(.ts)로 지정됨
        assert card.target_path is not None
        assert card.target_path.suffix == ".ts"


# 15. 중단된 작업에 대해 설정을 변경하고 동일 URL 재입력 시 최신 변경 설정을 따르는지 검증
def test_stopped_vod_redownload_applies_new_settings_quality_and_extension(
    main_window, qtbot
):
    """URL 입력 -> 설정에서 기본화질/확장자 변경 -> 작업 중단 -> 동일 URL 재시작 시 최신 설정을 따르는지 검증."""
    # 1. 초기 설정: 1080p, .mp4, 자동 다운로드 OFF
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

        # 첫 번째 입력
        main_window.url_input.setText(test_url)
        main_window.download_btn.click()
        qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

        card = main_window.task_list_widget.get_all_cards()[0]
        assert card.status == TaskStatus.READY
        assert card.quality_combo.currentText() == "1080p60"
        assert card.ext_combo.currentText() == ".mp4"
        assert "1080p60" in card.status_label.text()

        # 2. 작업 중단 (STOPPED)
        card.status = TaskStatus.STOPPED
        card._update_display()
        assert card.status == TaskStatus.STOPPED

        # 3. 환경설정에서 기본 화질을 '720p', 기본 확장자를 '.ts'로 변경
        update_current_settings(
            vod_auto_download=False,
            default_quality="720p",
            file_extension=".ts",
        )

        # 4. 동일 URL을 다시 입력하여 재다운로드 승인
        with patch.object(main_window, "_confirm_redownload_dialog", return_value=True):
            main_window.url_input.setText(test_url)
            main_window.download_btn.click()
            qtbot.waitUntil(lambda: main_window.download_btn.isEnabled(), timeout=2000)

            # 5. 재시작된 카드의 4번 위치가 이전 설정(1080p, .mp4)이 아닌 최신 변경 설정(720p, .ts)을 따르는지 검증
            assert card.status == TaskStatus.READY
            assert card.quality_combo.currentText() == "720p"
            assert card.ext_combo.currentText() == ".ts"
            assert "720p" in card.status_label.text()
            assert card.selected_quality == "720p"


# 16. 모달 대화상자 확인/취소 버튼 및 확인 하이라이트(기본 버튼/스타일) 검증
def test_confirm_modal_buttons_and_highlight(qtbot):
    """모달에서 Yes/No 대신 '확인'/'취소' 버튼을 사용하고 '확인'에 기본 하이라이트가 적용되는지 검증."""
    from chzzk_downloader.gui.dialogs import create_confirm_box

    msg_box, confirm_btn, cancel_btn = create_confirm_box(
        parent=None,
        title="테스트 제목",
        text="테스트 내용",
    )
    qtbot.addWidget(msg_box)

    # 1. 버튼 텍스트 확인
    assert confirm_btn.text() == "확인"
    assert cancel_btn.text() == "취소"

    # 2. 확인 버튼에 defaultButton 설정 및 하이라이트 스타일 확인
    assert msg_box.defaultButton() == confirm_btn
    assert "#2563eb" in confirm_btn.styleSheet()
    assert "font-weight: bold" in confirm_btn.styleSheet()

    # 3. danger 옵션(예: 쿠키 초기화) 시 빨간색 하이라이트 확인
    danger_box, danger_confirm, _ = create_confirm_box(
        parent=None,
        title="위험 삭제",
        text="정말 삭제하시겠습니까?",
        is_danger=True,
    )
    qtbot.addWidget(danger_box)
    assert danger_box.defaultButton() == danger_confirm
    assert "#ef4444" in danger_confirm.styleSheet()
