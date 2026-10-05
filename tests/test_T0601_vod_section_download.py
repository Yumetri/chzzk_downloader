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

    def test_build_vod_download_opts_injects_ffmpeg_to_os_environ_path(
        self, monkeypatch, tmp_path
    ) -> None:
        """yt-dlp의 FFmpegFD가 시스템 PATH에서만 ffmpeg를 탐색하므로, build_vod_download_opts 시 os.environ['PATH']에 ffmpeg 디렉터리가 주입되어야 한다."""
        import os
        import sys

        fake_bin_dir = tmp_path / "custom_bin"
        fake_bin_dir.mkdir()
        fake_ffmpeg = fake_bin_dir / (
            "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        )
        fake_ffmpeg.touch()

        # 격리된 PATH 설정 (fake_bin_dir 미포함)
        monkeypatch.setenv("PATH", str(tmp_path / "dummy"))
        monkeypatch.setattr(
            "chzzk_downloader.core.ffmpeg_manager.get_ffmpeg_path",
            lambda: fake_ffmpeg,
        )

        spec = TaskSpec(
            task_id="test_task",
            video_url="https://chzzk.naver.com/video/12345",
            is_live=False,
            title="테스트",
            streamer="스트리머",
            selected_quality="1080p",
            selected_ext=".mp4",
            save_path=tmp_path / "video.mp4",
            section_start=10.0,
            section_end=20.0,
        )

        build_vod_download_opts(spec)

        # os.environ["PATH"]에 fake_bin_dir이 추가되었는지 검증
        current_paths = os.environ.get("PATH", "").split(os.pathsep)
        assert str(fake_bin_dir) in current_paths

    def test_build_vod_download_opts_no_duplicate_path_injection(
        self, monkeypatch, tmp_path
    ) -> None:
        """이미 PATH에 ffmpeg 디렉터리가 존재하는 경우 중복 주입하지 않는지 검증."""
        import os
        import sys

        fake_bin_dir = tmp_path / "custom_bin"
        fake_bin_dir.mkdir()
        fake_ffmpeg = fake_bin_dir / (
            "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        )
        fake_ffmpeg.touch()

        # 이미 PATH에 포함된 상태
        monkeypatch.setenv("PATH", f"{fake_bin_dir}{os.pathsep}{tmp_path / 'dummy'}")
        monkeypatch.setattr(
            "chzzk_downloader.core.ffmpeg_manager.get_ffmpeg_path",
            lambda: fake_ffmpeg,
        )

        spec = TaskSpec(
            task_id="test_task_dup",
            video_url="https://chzzk.naver.com/video/12345",
            is_live=False,
            title="테스트",
            streamer="스트리머",
            selected_quality="1080p",
            selected_ext=".mp4",
            save_path=tmp_path / "video.mp4",
            section_start=10.0,
            section_end=20.0,
        )

        build_vod_download_opts(spec)

        current_paths = os.environ.get("PATH", "").split(os.pathsep)
        assert current_paths.count(str(fake_bin_dir)) == 1

    def test_prepare_ytdlp_ffmpeg_clears_stale_cache_and_enables_available(
        self, monkeypatch, tmp_path
    ) -> None:
        """yt-dlp의 캐시가 False로 오염된 상태에서도 prepare_ytdlp_ffmpeg 호출 시 캐시가 무효화되고 PATH가 주입되어야 한다."""
        import os
        import sys

        from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor

        from chzzk_downloader.core.ytdlp import prepare_ytdlp_ffmpeg

        fake_bin_dir = tmp_path / "custom_bin"
        fake_bin_dir.mkdir()
        fake_ffmpeg = fake_bin_dir / (
            "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        )
        fake_ffmpeg.touch()

        # 1. 오염된 캐시 및 잘못된 PATH 설정
        monkeypatch.setenv("PATH", str(tmp_path / "dummy"))
        monkeypatch.setattr(
            "chzzk_downloader.core.ffmpeg_manager.get_ffmpeg_path",
            lambda: fake_ffmpeg,
        )
        cache = vars(FFmpegPostProcessor)["_version_cache"]
        cache["ffmpeg"] = False

        # 2. prepare_ytdlp_ffmpeg 실행
        prepare_ytdlp_ffmpeg()

        # 3. 캐시에서 'ffmpeg': False가 제거되었고, PATH에 주입되었는지 단언
        assert cache.get("ffmpeg") is not False
        current_paths = os.environ.get("PATH", "").split(os.pathsep)
        assert str(fake_bin_dir) in current_paths

    def test_prepare_ytdlp_ffmpeg_ensures_chzzk_hook_called(self, monkeypatch) -> None:
        """prepare_ytdlp_ffmpeg가 호출될 때 네이버 MPD DASH 호환 훅도 함께 보장되어야 한다."""
        from unittest.mock import MagicMock

        import chzzk_downloader.core.ytdlp as ytdlp_mod
        from chzzk_downloader.core.ytdlp import prepare_ytdlp_ffmpeg

        mock_hook = MagicMock()
        monkeypatch.setitem(vars(ytdlp_mod), "_ensure_chzzk_hook", mock_hook)

        prepare_ytdlp_ffmpeg()
        mock_hook.assert_called_once()

    def test_prepare_ytdlp_ffmpeg_handles_none_ffmpeg_path_gracefully(
        self, monkeypatch
    ) -> None:
        """시스템에 FFmpeg가 전혀 감지되지 않아 None을 반환하더라도 예외 없이 무사히 완료되어야 한다."""
        from chzzk_downloader.core.ytdlp import prepare_ytdlp_ffmpeg

        monkeypatch.setattr(
            "chzzk_downloader.core.ffmpeg_manager.get_ffmpeg_path",
            lambda: None,
        )
        # 예외가 발생하지 않아야 함
        prepare_ytdlp_ffmpeg()

    def test_build_vod_download_opts_triggers_prepare_ytdlp_ffmpeg(
        self, monkeypatch, tmp_path
    ) -> None:
        """build_vod_download_opts 호출 시 prepare_ytdlp_ffmpeg가 연동 실행되어 캐시가 클리어되는지 검증."""
        from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor

        cache = vars(FFmpegPostProcessor)["_version_cache"]
        cache["ffmpeg"] = False

        fake_bin_dir = tmp_path / "custom_bin"
        fake_bin_dir.mkdir()
        fake_ffmpeg = fake_bin_dir / "ffmpeg.exe"
        fake_ffmpeg.touch()

        monkeypatch.setattr(
            "chzzk_downloader.core.ffmpeg_manager.get_ffmpeg_path",
            lambda: fake_ffmpeg,
        )

        spec = TaskSpec(
            task_id="test_opts_cache",
            video_url="https://chzzk.naver.com/video/12345",
            is_live=False,
            title="테스트",
            streamer="스트리머",
            selected_quality="1080p",
            selected_ext=".mp4",
            save_path=tmp_path / "video.mp4",
            section_start=10.0,
            section_end=20.0,
        )

        build_vod_download_opts(spec)

        assert cache.get("ffmpeg") is not False

    def test_build_vod_download_opts_includes_extractor_retries(self, tmp_path) -> None:
        """네트워크 일시 단절 방어를 위해 extractor_retries가 5 이상으로 설정되어야 한다."""
        spec = TaskSpec(
            task_id="test_extractor_retries",
            video_url="https://chzzk.naver.com/video/12345",
            is_live=False,
            title="테스트",
            streamer="스트리머",
            selected_quality="1080p",
            selected_ext=".mp4",
            save_path=tmp_path / "video.mp4",
        )
        opts = build_vod_download_opts(spec)
        assert opts.get("extractor_retries", 0) >= 5

    def test_chzzk_extract_retries_transient_incomplete_read(self, monkeypatch) -> None:
        """네이버 MPD XML 다운로드 중 IncompleteRead 일시 오류 발생 시 재시도하여 회복해야 한다."""
        from yt_dlp.extractor.chzzk import CHZZKVideoIE
        from yt_dlp.utils import ExtractorError

        from chzzk_downloader.core.ytdlp import prepare_ytdlp_ffmpeg

        prepare_ytdlp_ffmpeg()

        attempts = 0

        def flaky_mpd(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ExtractorError(
                    "Error reading response (caused by IncompleteRead)"
                )
            return ([], {})

        # MPD 파싱을 flaky_mpd로 모킹하고 가짜 비디오 메타데이터 제공
        monkeypatch.setattr(
            CHZZKVideoIE,
            "_download_json",
            lambda *a, **kw: {
                "content": {
                    "videoId": "12345",
                    "inKey": "key_abc",
                    "vodStatus": "ABR_HLS",
                    "videoTitle": "테스트 제목",
                }
            },
        )
        monkeypatch.setattr(
            CHZZKVideoIE,
            "_extract_mpd_formats_and_subtitles",
            flaky_mpd,
        )

        # 훅이 적용된 extract 실행
        import yt_dlp

        ydl = yt_dlp.YoutubeDL({"quiet": True})
        ie_instance = CHZZKVideoIE(ydl)
        result = ie_instance.extract("https://chzzk.naver.com/video/12345")
        assert result["id"] == "12345"
        assert result["title"] == "테스트 제목"
        assert attempts == 2

    def test_chzzk_extract_does_not_retry_permanent_error(self, monkeypatch) -> None:
        """404 Not Found 등 영구적 오류 발생 시에는 재시도 대기 없이 1회만에 즉시 예외가 전파되어야 한다."""
        import pytest
        import yt_dlp
        from yt_dlp.extractor.chzzk import CHZZKVideoIE
        from yt_dlp.utils import ExtractorError

        from chzzk_downloader.core.ytdlp import prepare_ytdlp_ffmpeg

        prepare_ytdlp_ffmpeg()

        attempts = 0

        def permanent_fail(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            raise ExtractorError("HTTP Error 404: Not Found")

        monkeypatch.setattr(CHZZKVideoIE, "_download_json", permanent_fail)

        ydl = yt_dlp.YoutubeDL({"quiet": True})
        ie_instance = CHZZKVideoIE(ydl)
        with pytest.raises(ExtractorError, match="404: Not Found"):
            ie_instance.extract("https://chzzk.naver.com/video/99999")

        assert attempts == 1

    def test_adjust_live_open_date_with_section_offset(self) -> None:
        """라이브 시작일시에 구간 시작 시간(초)을 가산하여 보정된 일시를 반환하고 파일명에 반영해야 한다."""
        from chzzk_downloader.core.filename_generator import (
            adjust_live_open_date,
            generate_vod_filename,
        )

        # 1. 2시간 가산 (15:00 + 7200초 = 17:00)
        adjusted = adjust_live_open_date("2026-09-25 15:00", 7200.0)
        assert adjusted == "2026-09-25 17:00"

        # 2. 초 단위 가산 (15:00:00 + 125초 = 15:02:05)
        adjusted_sec = adjust_live_open_date("2026-09-25 15:00:00", 125.0)
        assert adjusted_sec == "2026-09-25 15:02:05"

        # 3. 파일명 생성기 연동 검증
        info = VodInfo(
            video_no="15368883",
            video_title="잠시 에반게리온 분석방",
            channel_name="소풍왔니",
            duration=9742,
            live_open_date="2026-09-25 15:00",
        )
        fname = generate_vod_filename(
            info,
            section_start=7200.0,
            section_end=7343.0,
        )
        # 15:00이 아닌 보정된 17:00 (전각 콜론 17：00)이어야 함
        assert "17：00" in fname
        assert "15：00" not in fname

    def test_task_card_section_effective_duration_display(self, qtbot) -> None:
        """구간 다운로드 설정 시 3번 위치의 영상 길이가 전체 길이가 아닌 실제 구간 길이로 표시되어야 한다."""
        from chzzk_downloader.core.task_models import TaskStatus
        from chzzk_downloader.gui.task_card import TaskCardWidget

        card = TaskCardWidget(
            task_id="t_dur", raw_url="https://chzzk.naver.com/video/1"
        )
        qtbot.addWidget(card)

        info = VodInfo(
            video_no="1",
            video_title="테스트",
            channel_name="스트리머",
            duration=7200,  # 2시간
        )
        card.update_with_vod_info(info)

        # 구간 10분 설정 (3600초 ~ 4200초)
        card.section_popup.set_section_range(3600.0, 4200.0)

        # READY 상태 3번 위치 라벨에 유효 구간 길이(10:00 또는 00:10:00)가 반영되어야 함
        assert "02:00:00" not in card.status_label.text()
        assert "10:00" in card.status_label.text()

        # COMPLETED 상태로 전이 시에도 3번 위치에 실제 구간 길이(10:00)가 반영되어야 함
        card.set_task_status(TaskStatus.COMPLETED)
        assert "02:00:00" not in card.time_metric_label.text()
        assert "10:00" in card.time_metric_label.text()

    def test_task_card_completed_displays_file_size(self, qtbot, tmp_path) -> None:
        """set_completed 호출 시 최종 파일의 크기가 3번 위치 size_metric_label에 즉시 표시되어야 한다."""
        from chzzk_downloader.gui.task_card import TaskCardWidget

        card = TaskCardWidget(
            task_id="t_size", raw_url="https://chzzk.naver.com/video/2"
        )
        qtbot.addWidget(card)

        test_file = tmp_path / "video.mp4"
        test_file.write_bytes(b"x" * 1024 * 1024 * 3)  # 3 MB

        # 1. 상태 변경 시그널이 먼저 도달하여 COMPLETED로 전이 (이때는 final_file_path 미지정으로 '--' 상태)
        card.set_task_status(TaskStatus.COMPLETED)
        assert card.size_metric_label.text() == "--"

        # 2. task_completed 시그널이 도달하여 set_completed 호출
        card.set_completed(test_file)

        # 3. set_completed 내부에서 강제 갱신되어 3번 위치 용량 라벨이 '--'가 아닌 실제 용량(3.0 MB)으로 렌더링되어야 함
        assert card.size_metric_label.text() != "--"
        assert "3.0 MB" in card.size_metric_label.text()

    def test_section_progress_poller_tracks_file_growth(self, qtbot, tmp_path) -> None:
        from chzzk_downloader.core.task_models import TaskProgress
        from chzzk_downloader.gui.section_poller import SectionProgressPoller

        target_file = tmp_path / "section_out.mp4"
        part_file = tmp_path / "section_out.mp4.part"
        part_file.write_bytes(b"x" * 1024 * 1024)  # 1 MB 시작

        emitted_progress: list[TaskProgress] = []

        poller = SectionProgressPoller(
            task_id="t_poll",
            save_path=target_file,
            poll_interval_sec=0.05,
            progress_callback=emitted_progress.append,
        )

        poller.start()
        try:
            # 파일이 2 MB로 증가
            part_file.write_bytes(b"x" * 1024 * 1024 * 2)
            qtbot.waitUntil(lambda: len(emitted_progress) > 0, timeout=1000)

            last = emitted_progress[-1]
            assert last.downloaded_bytes >= 1024 * 1024
            assert last.task_id == "t_poll"
        finally:
            poller.stop()

    def test_vod_download_worker_uses_poller_for_section_download(
        self, tmp_path, monkeypatch
    ) -> None:
        """VodDownloadWorker가 구간 다운로드 시 비동기 진행률 폴러를 가동하고 완료 시 정리해야 한다."""
        from chzzk_downloader.gui.workers import VodDownloadWorker

        target_file = tmp_path / "video.mp4"

        spec = TaskSpec(
            task_id="t_worker_sec",
            video_url="https://chzzk.naver.com/video/15368883",
            is_live=False,
            title="테스트",
            streamer="스트리머",
            selected_quality="1080p",
            selected_ext="mp4",
            save_path=target_file,
            section_start=10.0,
            section_end=20.0,
        )

        worker = VodDownloadWorker(spec)

        # fake download: yt-dlp download를 모킹하여 파일 생성
        class FakeYDL:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def __enter__(self) -> "FakeYDL":
                return self

            def __exit__(self, *args) -> None:
                pass

            def download(self, urls: list[str]) -> None:
                target_file.write_bytes(b"x" * 1024 * 512)

        import yt_dlp

        monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)

        worker.run()
        assert target_file.is_file()

    def test_adjust_live_open_date_edge_cases(self) -> None:
        """라이브 시작일시 보정 함수의 다양한 엣지 케이스(빈 문자열, 날짜 단독, 음수/초과 오프셋 등)를 안전하게 처리해야 한다."""
        from chzzk_downloader.core.filename_generator import adjust_live_open_date

        # 1. 빈 문자열 또는 공백
        assert adjust_live_open_date("", 3600.0) == ""
        assert adjust_live_open_date("   ", 3600.0) == "   "

        # 2. 오프셋 0초
        assert adjust_live_open_date("2026-09-25 15:00", 0.0) == "2026-09-25 15:00"

        # 3. 날짜만 있는 경우 (시간 없음) -> 원본 보존
        assert adjust_live_open_date("2026-09-25", 3600.0) == "2026-09-25"

        # 4. 지원하지 않는 잘못된 형식 -> 원본 보존
        assert (
            adjust_live_open_date("invalid_date_format", 3600.0)
            == "invalid_date_format"
        )

        # 5. 자정 롤오버 (23:30 + 1시간 = 익일 00:30)
        adjusted_midnight = adjust_live_open_date("2026-09-25 23:30", 3600.0)
        assert adjusted_midnight == "2026-09-26 00:30"

        # 6. 연말 롤오버 (2026-12-31 23:50 + 20분 = 2027-01-01 00:10)
        adjusted_year = adjust_live_open_date("2026-12-31 23:50", 1200.0)
        assert adjusted_year == "2027-01-01 00:10"

    def test_section_progress_poller_robustness_on_file_deletion_and_negative_speed(
        self, qtbot, tmp_path
    ) -> None:
        from chzzk_downloader.core.task_models import TaskProgress
        from chzzk_downloader.gui.section_poller import SectionProgressPoller

        target_file = tmp_path / "robust.mp4"
        part_file = tmp_path / "robust.mp4.part"
        part_file.write_bytes(b"x" * 1024 * 512)

        emitted: list[TaskProgress] = []
        poller = SectionProgressPoller(
            task_id="t_robust",
            save_path=target_file,
            poll_interval_sec=0.03,
            progress_callback=emitted.append,
        )

        poller.start()
        try:
            # 파일 삭제 시뮬레이션
            part_file.unlink(missing_ok=True)
            qtbot.waitUntil(lambda: len(emitted) > 0, timeout=1000)

            # 크래시 없이 동작 확인
            last = emitted[-1]
            assert last.speed_bytes_sec >= 0.0
        finally:
            poller.stop()
            # stop 다중 호출 안전성 확인
            poller.stop()

    def test_task_card_completed_handles_missing_or_empty_path(self, qtbot) -> None:
        """존재하지 않거나 빈 경로로 set_completed가 호출되어도 크래시 없이 안전하게 처리되어야 한다."""
        from chzzk_downloader.gui.task_card import TaskCardWidget

        card = TaskCardWidget(
            task_id="t_empty", raw_url="https://chzzk.naver.com/video/3"
        )
        qtbot.addWidget(card)

        # 빈 경로 호출
        card.set_completed("")
        assert card.status == TaskStatus.COMPLETED
        assert card.size_metric_label.text() == "--"

        # 존재하지 않는 경로 호출
        card.set_completed("C:/non_existent_dir/non_existent_file.mp4")
        assert card.status == TaskStatus.COMPLETED
        assert card.size_metric_label.text() == "--"
