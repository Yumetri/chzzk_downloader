from pathlib import Path

import pytest

from chzzk_downloader.core.filename_generator import generate_vod_filename
from chzzk_downloader.core.section_parser import (
    format_section_suffix,
    format_timestamp,
    parse_timestamp,
    validate_section,
)
from chzzk_downloader.core.settings_manager import AppSettings
from chzzk_downloader.core.task_models import TaskSpec, TaskStatus
from chzzk_downloader.core.ytdlp import VodInfo
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.section_popup import SectionPopup
from chzzk_downloader.gui.task_card import TaskCardWidget
from chzzk_downloader.gui.workers import build_vod_download_opts


class TestSectionParser:
    """타임스탬프 파싱 및 유효성 검증 순수 도메인 함수 테스트."""

    def test_parse_timestamp_seconds_int_and_float(self) -> None:
        """초 단위 정수, 부동소수점 및 문자열 숫자를 올바르게 초 단위 실수로 파싱한다."""
        assert parse_timestamp(0) == 0.0
        assert parse_timestamp(120) == 120.0
        assert parse_timestamp(120.5) == 120.5
        assert parse_timestamp("45") == 45.0
        assert parse_timestamp("45.25") == 45.25

    def test_parse_timestamp_colon_formats(self) -> None:
        """'SS', 'M:SS', 'MM:SS', 'H:MM:SS', 'HH:MM:SS' 등 콜론 형식을 초 단위 실수로 파싱한다."""
        assert parse_timestamp("0:30") == 30.0
        assert parse_timestamp("01:30") == 90.0
        assert parse_timestamp("1:00:00") == 3600.0
        assert parse_timestamp("01:23:45") == 5025.0
        assert parse_timestamp("01:23:45.50") == 5025.5
        assert parse_timestamp("0:0:0.00") == 0.0

    def test_parse_timestamp_rejects_invalid_values(self) -> None:
        """음수, 콜론 3개 이상, 잘못된 문자열 등 비정상 값을 거부하고 ValueError를 발생시킨다."""
        with pytest.raises(ValueError):
            parse_timestamp("-10")
        with pytest.raises(ValueError):
            parse_timestamp("abc")
        with pytest.raises(ValueError):
            parse_timestamp("1:2:3:4")
        with pytest.raises(ValueError):
            parse_timestamp("01:65:00")  # 분이 60 이상
        with pytest.raises(ValueError):
            parse_timestamp("01:20:65")  # 초가 60 이상

    def test_validate_section_valid_range(self) -> None:
        """0 <= start < end <= duration 정상 범위를 검증하고 부동소수점 튜플을 반환한다."""
        start, end = validate_section(10, 100, duration=200)
        assert start == 10.0
        assert end == 100.0

        start, end = validate_section("00:10:00", "00:25:30", duration=3600)
        assert start == 600.0
        assert end == 1530.0

    def test_validate_section_rejects_inverted_range(self) -> None:
        """시작 시각이 종료 시각 이상인 경우 거부한다."""
        with pytest.raises(ValueError, match="시작 시각은 종료 시각보다 빨라야"):
            validate_section(100, 10, duration=200)

        with pytest.raises(ValueError, match="시작 시각은 종료 시각보다 빨라야"):
            validate_section(100, 100, duration=200)

    def test_validate_section_rejects_exceeding_duration(self) -> None:
        """종료 시각이 VOD 전체 길이를 초과하는 경우 거부한다."""
        with pytest.raises(ValueError, match="전체 영상 길이를 초과"):
            validate_section(10, 300, duration=200)

    def test_validate_section_rejects_negative_start(self) -> None:
        """시작 시각이 음수인 경우 거부한다."""
        with pytest.raises(ValueError, match="음수일 수 없습니다"):
            validate_section(-5, 50, duration=100)

    def test_format_timestamp_and_section_suffix(self) -> None:
        """타임스탬프 서식 및 파일명용 구간 접미사를 규격에 맞게 생성한다."""
        assert format_timestamp(0) == "00:00:00"
        assert format_timestamp(5025) == "01:23:45"
        assert format_timestamp(5025.5, use_fraction=True) == "01:23:45.50"

        suffix = format_section_suffix(600, 1530)
        assert suffix == "[00_10_00-00_25_30]"


class TestSectionFilename:
    """구간 다운로드 파일명 서식 및 접미사 부착 테스트."""

    def test_generate_vod_filename_with_section(self) -> None:
        """구간이 지정된 경우 파일명에 [시작-종료] 접미사가 올바르게 부착된다."""
        info = VodInfo(
            video_no="12345",
            video_title="테스트 방송",
            channel_name="치즈스트리머",
            duration=3600,
        )
        fname = generate_vod_filename(
            info, ext="mp4", section_start=600, section_end=1530
        )
        assert fname == "[치즈스트리머] 테스트 방송 (12345) [00_10_00-00_25_30].mp4"

    def test_generate_vod_filename_without_section(self) -> None:
        """구간이 지정되지 않은 경우 기존과 동일하게 접미사 없이 생성된다."""
        info = VodInfo(
            video_no="12345",
            video_title="테스트 방송",
            channel_name="치즈스트리머",
            duration=3600,
        )
        fname = generate_vod_filename(info, ext="mp4")
        assert fname == "[치즈스트리머] 테스트 방송 (12345).mp4"


class TestSectionWorkerOpts:
    """VodDownloadWorker yt-dlp 옵션 빌드 시 download_ranges 연동 테스트."""

    def test_build_vod_download_opts_injects_download_ranges(self) -> None:
        """TaskSpec에 구간이 설정된 경우 yt-dlp 옵션에 download_ranges가 주입된다."""
        spec = TaskSpec(
            task_id="task-123",
            video_url="https://chzzk.naver.com/video/12345",
            save_path="downloads/video.mp4",
            section_start=60.0,
            section_end=180.0,
        )
        opts = build_vod_download_opts(spec)
        assert "download_ranges" in opts
        assert callable(opts["download_ranges"])

    def test_build_vod_download_opts_without_section(self) -> None:
        """TaskSpec에 구간이 없는 경우 download_ranges가 주입되지 않는다."""
        spec = TaskSpec(
            task_id="task-123",
            video_url="https://chzzk.naver.com/video/12345",
            save_path="downloads/video.mp4",
        )
        opts = build_vod_download_opts(spec)
        assert "download_ranges" not in opts


class TestSectionPopupWidget:
    """구간 설정 팝업 위젯 UI 인터랙션 및 유효성 피드백 테스트."""

    def test_popup_default_state(self, qtbot) -> None:
        """기본 상태에서 체크박스는 해제되어 있고 입력창은 비활성화되며 전체 구간(None, None)을 반환한다."""
        popup = SectionPopup()
        qtbot.addWidget(popup)

        assert not popup.start_check.isChecked()
        assert not popup.end_check.isChecked()
        assert not popup.start_edit.isEnabled()
        assert not popup.end_edit.isEnabled()
        assert popup.get_section_range() == (None, None)
        assert popup.is_valid() is True

    def test_popup_checkbox_toggle_enables_inputs(self, qtbot) -> None:
        """체크박스를 클릭하면 해당 입력창이 활성화된다."""
        popup = SectionPopup()
        qtbot.addWidget(popup)

        popup.start_check.setChecked(True)
        assert popup.start_edit.isEnabled()

        popup.end_check.setChecked(True)
        assert popup.end_edit.isEnabled()

    def test_popup_partial_selection_uses_endpoints(self, qtbot) -> None:
        """한쪽 체크 해제 시 시작은 0초, 종료는 영상 전체 길이를 자동 기본값으로 적용한다."""
        popup = SectionPopup()
        qtbot.addWidget(popup)
        popup.set_duration(3600.0)

        # 시작만 체크
        popup.start_check.setChecked(True)
        popup.start_edit.setText("00:10:00")
        assert popup.get_section_range() == (600.0, 3600.0)

        # 종료만 체크
        popup.start_check.setChecked(False)
        popup.end_check.setChecked(True)
        popup.end_edit.setText("00:20:00")
        assert popup.get_section_range() == (0.0, 1200.0)

    def test_popup_validation_rejects_invalid_range(self, qtbot) -> None:
        """시작 시각이 종료 시각 이상인 경우 에러를 감지하고 유효하지 않음을 알린다."""
        popup = SectionPopup()
        qtbot.addWidget(popup)
        popup.show()
        popup.set_duration(3600.0)

        popup.start_check.setChecked(True)
        popup.end_check.setChecked(True)
        popup.start_edit.setText("00:30:00")
        popup.end_edit.setText("00:10:00")  # 시작 > 종료

        assert popup.is_valid() is False
        assert popup.error_label.isVisible()


class TestTaskCardSectionIntegration:
    """TaskCardWidget과 구간 설정 기능 연동 테스트."""

    def test_regular_vod_shows_section_button(self, qtbot) -> None:
        """정식 VOD(can_section_download=True)는 구간 설정 버튼이 노출된다."""
        card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/12345")
        qtbot.addWidget(card)
        card.show()

        info = VodInfo(
            video_no="12345",
            video_title="정식 VOD",
            channel_name="스트리머",
            duration=3600,
            can_section_download=True,
        )
        card.update_with_vod_info(info)

        assert card.section_btn.isVisible() is True

    def test_replay_vod_hides_section_button(self, qtbot) -> None:
        """빠른 다시보기(can_section_download=False)는 구간 설정 버튼이 아예 숨겨진다."""
        card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/12345")
        qtbot.addWidget(card)
        card.show()

        info = VodInfo(
            video_no="12345",
            video_title="빠른 다시보기",
            channel_name="스트리머",
            duration=3600,
            can_section_download=False,
        )
        card.update_with_vod_info(info)

        assert card.section_btn.isVisible() is False

    def test_task_spec_reflects_configured_section(self, qtbot) -> None:
        """구간을 설정하면 TaskSpec과 파일명에 구간 정보가 올바르게 반영된다."""
        card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/12345")
        qtbot.addWidget(card)
        card.show()

        info = VodInfo(
            video_no="12345",
            video_title="테스트 영상",
            channel_name="스트리머",
            duration=3600,
            can_section_download=True,
        )
        card.update_with_vod_info(info)

        card.section_popup.start_check.setChecked(True)
        card.section_popup.start_edit.setText("00:05:00")
        card.section_popup.end_check.setChecked(True)
        card.section_popup.end_edit.setText("00:15:00")

        spec = card.get_task_spec()
        assert spec.section_start == 300.0
        assert spec.section_end == 900.0
        assert "[00_05_00-00_15_00]" in str(spec.save_path)

    def test_trigger_start_download_blocks_invalid_section(self, qtbot) -> None:
        """잘못된 구간이 설정된 상태에서 trigger_start_download 호출 시 download_blocked를 방출하고 차단한다."""
        card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/12345")
        qtbot.addWidget(card)
        card.show()

        info = VodInfo(
            video_no="12345",
            video_title="테스트 영상",
            channel_name="스트리머",
            duration=3600,
            can_section_download=True,
        )
        card.update_with_vod_info(info)

        # 시작 > 종료 비정상 입력
        card.section_popup.start_check.setChecked(True)
        card.section_popup.start_edit.setText("00:20:00")
        card.section_popup.end_check.setChecked(True)
        card.section_popup.end_edit.setText("00:10:00")

        blocked_signals: list[str] = []
        card.download_blocked.connect(blocked_signals.append)

        result = card.trigger_start_download()
        assert result is False
        assert len(blocked_signals) == 1
        assert "올바른 구간을 입력해주세요" in blocked_signals[0]


class TestMainWindowSectionAutoDownload:
    """MainWindow에서 정식 VOD와 빠른 다시보기의 자동 다운로드 분기 동작 테스트."""

    def test_regular_vod_stays_in_ready_when_auto_download_off(
        self, qtbot, monkeypatch
    ) -> None:
        """vod_auto_download가 False일 때 정식 VOD는 구간 설정을 위해 READY 상태로 대기한다."""
        monkeypatch.setattr(
            "chzzk_downloader.core.settings_manager.get_current_settings",
            lambda: AppSettings(
                download_dir=Path("downloads"), vod_auto_download=False
            ),
        )

        win = MainWindow()
        qtbot.addWidget(win)
        win.show()

        card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/12345")
        win.task_list_widget.add_task_card(card)

        info = VodInfo(
            video_no="12345",
            video_title="정식 방송",
            channel_name="스트리머",
            duration=3600,
            can_section_download=True,
        )
        win.apply_vod_check_result(info, card)

        assert card.status == TaskStatus.READY
        assert card.section_btn.isVisible() is True

    def test_replay_vod_triggers_auto_download_when_enabled(
        self, qtbot, monkeypatch
    ) -> None:
        """빠른 다시보기(can_section_download=False)는 vod_auto_download가 True일 때 즉시 시작을 트리거한다."""
        monkeypatch.setattr(
            "chzzk_downloader.core.settings_manager.get_current_settings",
            lambda: AppSettings(download_dir=Path("downloads"), vod_auto_download=True),
        )

        win = MainWindow()
        qtbot.addWidget(win)

        card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/12345")
        win.task_list_widget.add_task_card(card)

        triggered: list[bool] = []
        monkeypatch.setattr(
            card, "trigger_start_download", lambda: triggered.append(True)
        )

        info = VodInfo(
            video_no="12345",
            video_title="빠른 다시보기 방송",
            channel_name="스트리머",
            duration=3600,
            can_section_download=False,
        )
        win.apply_vod_check_result(info, card)

        assert len(triggered) == 1

    def test_regular_vod_stays_in_ready_even_when_auto_download_enabled(
        self, qtbot, monkeypatch
    ) -> None:
        """정식 VOD(can_section_download=True)는 vod_auto_download가 True여도 구간 설정을 위해 항상 READY 상태로 대기한다."""
        monkeypatch.setattr(
            "chzzk_downloader.core.settings_manager.get_current_settings",
            lambda: AppSettings(download_dir=Path("downloads"), vod_auto_download=True),
        )

        win = MainWindow()
        qtbot.addWidget(win)
        win.show()

        card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/12345")
        win.task_list_widget.add_task_card(card)

        triggered: list[bool] = []
        monkeypatch.setattr(
            card, "trigger_start_download", lambda: triggered.append(True)
        )

        info = VodInfo(
            video_no="12345",
            video_title="정식 방송",
            channel_name="스트리머",
            duration=3600,
            can_section_download=True,
        )
        win.apply_vod_check_result(info, card)

        # 방안 B: 정식 VOD는 vod_auto_download가 True여도 자동 시작하지 않고 대기함
        assert len(triggered) == 0
        assert card.status == TaskStatus.READY
        assert card.section_btn.isVisible() is True


class TestSectionEdgeCases:
    """구간 다운로드 경계값 및 예외 상황 방어 테스트."""

    def test_format_timestamp_carry_over_at_59_seconds(self) -> None:
        """59.999초 등 소수점 반올림 경계에서 초가 60이 되지 않고 상위 분/시로 올림되는지 검증."""
        assert format_timestamp(59.999, use_fraction=True) == "00:01:00.00"
        assert format_timestamp(3599.999, use_fraction=True) == "01:00:00.00"

    def test_parse_timestamp_rejects_nan_and_inf_strings(self) -> None:
        """'nan', 'inf' 등의 문자열 입력 시 ValueError로 거부되는지 검증."""
        for invalid in ["nan", "NaN", "-nan", "inf", "-inf", "+inf", "1:nan:00"]:
            with pytest.raises(ValueError):
                parse_timestamp(invalid)

    def test_parse_timestamp_rejects_negative_colon_times(self) -> None:
        """'-0:30', '-0:00:15' 등 음수 부호가 포함된 콜론 시간 입력 시 ValueError로 거부되는지 검증."""
        for invalid in ["-0:30", "-00:15", "-0:00:10", "01:-05:00"]:
            with pytest.raises(ValueError):
                parse_timestamp(invalid)

    def test_task_card_reset_for_redownload_clears_section_popup(self, qtbot) -> None:
        """재다운로드 리셋 시 이전 구간 설정이 고착되지 않고 초기화되는지 검증."""
        card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/12345")
        qtbot.addWidget(card)
        info = VodInfo(
            video_no="12345",
            video_title="테스트 영상",
            channel_name="스트리머",
            duration=3600,
        )
        card.update_with_vod_info(info)

        card.section_popup.start_check.setChecked(True)
        card.section_popup.start_edit.setText("00:10:00")
        card.section_popup.end_check.setChecked(True)
        card.section_popup.end_edit.setText("00:20:00")
        assert card.section_popup.get_section_range() == (600.0, 1200.0)

        card.reset_for_redownload()
        assert card.section_popup.start_check.isChecked() is False
        assert card.section_popup.end_check.isChecked() is False
        assert card.section_popup.get_section_range() == (None, None)

    def test_task_card_hides_section_popup_on_download_start(self, qtbot) -> None:
        """다운로드 시작 시 열려있던 구간 설정 팝업이 자동으로 닫히는지 검증."""
        card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/12345")
        qtbot.addWidget(card)
        info = VodInfo(
            video_no="12345",
            video_title="테스트 영상",
            channel_name="스트리머",
            duration=3600,
        )
        card.update_with_vod_info(info)
        card.show()
        card.section_popup.show()
        assert card.section_popup.isVisible() is True

        card.trigger_start_download()
        assert card.section_popup.isVisible() is False

    def test_filename_generator_handles_zero_duration_with_open_end_section(
        self,
    ) -> None:
        """duration이 0이거나 미제공된 VOD에서 시작 시간만 지정 시 비정상 역전 접미사가 생성되지 않는지 검증."""
        info = VodInfo(
            video_no="12345",
            video_title="테스트 영상",
            channel_name="스트리머",
            duration=0,
        )
        name = generate_vod_filename(info, section_start=10.0, section_end=None)
        assert "[00_00_10-00_00_00]" not in name
