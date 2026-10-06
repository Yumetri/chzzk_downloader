from pathlib import Path
from typing import Any

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
        assert isinstance(result, dict)
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

    def test_section_download_poller_calculates_percentage_and_eta(
        self, tmp_path, qtbot
    ) -> None:
        """구간 다운로드 폴러가 estimated_total_bytes를 기반으로 0%가 아닌 유의미한 percentage와 ETA를 산출하는지 검증."""
        from chzzk_downloader.core.task_models import TaskProgress
        from chzzk_downloader.gui.section_poller import SectionProgressPoller

        target_file = tmp_path / "section_test.mp4"
        # 2MB 파일 생성
        target_file.write_bytes(b"x" * 2 * 1024 * 1024)

        emitted: list[TaskProgress] = []
        # 예상 용량 10MB
        poller = SectionProgressPoller(
            task_id="t_pct",
            save_path=target_file,
            poll_interval_sec=0.03,
            estimated_total_bytes=10 * 1024 * 1024,
            progress_callback=emitted.append,
        )
        poller.start()
        try:
            qtbot.waitUntil(lambda: len(emitted) > 0, timeout=1000)
            last = emitted[-1]
            assert last.total_bytes == 10 * 1024 * 1024
            assert last.percentage == 20.0
            assert "20.0%" in last.detailed_percentage_str
        finally:
            poller.stop()

    def test_section_download_cancel_kills_ffmpeg_and_preserves_media(
        self, tmp_path, qtbot
    ) -> None:
        """구간 다운로드 취소 시 활성 FFmpeg 프로세스에 kill이 호출되고, 생성된 유효 미디어 파일은 보존되는지 검증."""
        from unittest.mock import MagicMock

        from chzzk_downloader.core.task_models import TaskSpec
        from chzzk_downloader.gui.workers import VodDownloadWorker

        target_file = tmp_path / "section_media.mp4"
        # 1MB 기존 미디어 데이터 생성
        target_file.write_bytes(b"x" * 1024 * 1024)

        spec = TaskSpec(
            task_id="t_cancel_kill",
            video_url="https://chzzk.naver.com/video/1",
            save_path=target_file,
            section_start=0.0,
            section_end=60.0,
        )
        worker = VodDownloadWorker(spec)

        fake_proc = MagicMock()
        fake_proc.kill = MagicMock()
        # 가상 하위 서브프로세스 등록
        worker.register_subprocess(fake_proc)

        # 취소 실행
        worker.cancel()

        # 1. FFmpeg 프로세스에 kill이 즉시 호출되었는지 검증
        fake_proc.kill.assert_called_once()

        # 2. 유효 미디어 파일(>0B)은 디스크에 온전히 보존되어 있는지 음성 단언
        worker.cleanup_partial_files(delete_media=False)
        assert target_file.exists()
        assert target_file.stat().st_size == 1024 * 1024

    def test_task_spec_expected_total_bytes_calculated_from_section_and_bitrate(
        self, tmp_path, qtbot
    ) -> None:
        """TaskCard에서 구간 설정과 화질이 주어졌을 때 expected_total_bytes가 TaskSpec에 올바르게 계산되어 반영되는지 검증."""
        from chzzk_downloader.core.ytdlp import VodFormatInfo, VodInfo
        from chzzk_downloader.gui.task_card import TaskCardWidget

        card = TaskCardWidget(
            task_id="t_expected_bytes",
            raw_url="https://chzzk.naver.com/video/12345",
        )
        qtbot.addWidget(card)

        # 10분(600초) VOD, 1080p tbr=6000 kbps 메타데이터 설정
        card.vod_info = VodInfo(
            video_no="12345",
            video_title="비트레이트 테스트",
            channel_name="스트리머",
            duration=600,
            formats=[VodFormatInfo(format_id="1080p", resolution="1080p", tbr=6000.0)],
        )
        # 구간 0초 ~ 300초 (5분 = 300초)
        card.section_popup.set_section_range(0.0, 300.0)
        card.quality_combo.clear()
        card.quality_combo.addItem("1080p")

        spec = card.get_task_spec()
        # 6000 kbps = 6,000,000 bps = 750,000 B/s. 300초 = 225,000,000 B
        expected = int(6000.0 * 1000 / 8 * 300)
        assert spec.expected_total_bytes == expected

    def test_delete_file_safely_retries_on_temporary_file_lock(
        self, tmp_path, monkeypatch
    ) -> None:
        """Windows 파일 핸들 릴리즈 지연으로 첫 시도에 PermissionError가 발생해도 재시도를 통해 정상 삭제되는지 검증."""

        from chzzk_downloader.gui.task_card import _delete_file_safely

        test_file = tmp_path / "lock_test.mp4"
        test_file.write_bytes(b"data")

        attempts = 0
        real_unlink = Path.unlink

        def mock_unlink(path_obj, missing_ok=True):
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                raise PermissionError("다른 프로세스가 파일을 사용 중입니다.")
            real_unlink(path_obj, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", mock_unlink)
        # Windows shell32 SHFileOperation을 건너뛰도록 mocking
        monkeypatch.setattr("sys.platform", "linux")

        ok = _delete_file_safely(test_file)
        assert ok is True
        assert attempts == 2
        assert not test_file.exists()

    def test_section_poller_dynamic_expansion_when_actual_exceeds_estimated(
        self, tmp_path, qtbot
    ) -> None:
        """실제 파일 크기가 예상 크기보다 커져도 100%를 초과하지 않고 99% 이하로 부드럽게 동적 확장되는지 검증."""
        from chzzk_downloader.core.task_models import TaskProgress
        from chzzk_downloader.gui.section_poller import SectionProgressPoller

        test_file = tmp_path / "exceed.mp4"
        # 15MB 파일 (예상 10MB 초과)
        test_file.write_bytes(b"x" * 15 * 1024 * 1024)

        emitted: list[TaskProgress] = []
        poller = SectionProgressPoller(
            task_id="t_exceed",
            save_path=test_file,
            poll_interval_sec=0.03,
            estimated_total_bytes=10 * 1024 * 1024,
            progress_callback=emitted.append,
        )
        poller.start()
        try:
            qtbot.waitUntil(lambda: len(emitted) > 0, timeout=1000)
            last = emitted[-1]
            # 동적 확장으로 total_bytes가 15MB * 1.05 이상으로 커져야 함
            assert last.total_bytes >= 15 * 1024 * 1024
            assert last.percentage <= 99.0
            assert last.downloaded_bytes == 15 * 1024 * 1024
        finally:
            poller.stop()

    def test_worker_cancel_idempotent_and_safe_with_exited_process(
        self, tmp_path
    ) -> None:
        """프로세스가 이미 종료되었거나 다중 cancel 호출 시에도 크래시 없이 안전하게 멱등성을 유지하는지 검증."""
        from unittest.mock import MagicMock

        from chzzk_downloader.core.task_models import TaskSpec
        from chzzk_downloader.gui.workers import VodDownloadWorker

        spec = TaskSpec(
            task_id="t_idempotent",
            video_url="https://chzzk.naver.com/video/1",
            save_path=tmp_path / "out.mp4",
        )
        worker = VodDownloadWorker(spec)

        dead_proc = MagicMock()
        # kill 호출 시 이미 프로세스가 종료되어 OSError 발생 모사
        dead_proc.kill.side_effect = OSError("Process already dead")
        worker.register_subprocess(dead_proc)

        # 3회 연속 취소 호출해도 예외가 발생하지 않아야 함
        worker.cancel()
        worker.cancel()
        worker.cancel()

        assert worker.is_cancelled is True
        assert dead_proc.kill.call_count == 3

    def test_section_download_opts_include_avoid_negative_ts(self, tmp_path) -> None:
        """구간 다운로드 옵션에 FFmpeg 타임스탬프 리셋(-avoid_negative_ts make_zero) 인자가 포함되는지 검증."""
        from chzzk_downloader.core.task_models import TaskSpec
        from chzzk_downloader.core.ytdlp_opts import build_vod_download_opts

        spec = TaskSpec(
            task_id="t_ts_reset",
            video_url="https://chzzk.naver.com/video/123",
            save_path=tmp_path / "ts_test.mp4",
            section_start=3600.0,
            section_end=3900.0,
        )
        opts = build_vod_download_opts(spec)

        downloader_args = opts.get("downloader_args", {}).get("ffmpeg", [])
        postprocessor_args = opts.get("postprocessor_args", {}).get("ffmpeg", [])

        assert "-avoid_negative_ts" in downloader_args
        assert "make_zero" in downloader_args
        assert "-avoid_negative_ts" in postprocessor_args
        assert "make_zero" in postprocessor_args

    def test_task_card_stopped_and_completed_shows_actual_partial_duration(
        self, tmp_path, qtbot
    ) -> None:
        """구간 다운로드 중간 정지 시 3번 위치에 원본 전체 길이가 아닌 실제 다운로드된 구간 시간이 표시되고 완료 확정 시에도 유지되는지 검증."""
        from chzzk_downloader.core.task_models import TaskProgress, TaskStatus
        from chzzk_downloader.core.ytdlp import VodFormatInfo, VodInfo
        from chzzk_downloader.gui.task_card import TaskCardWidget

        card = TaskCardWidget(
            task_id="t_stopped_dur",
            raw_url="https://chzzk.naver.com/video/999",
        )
        qtbot.addWidget(card)

        dummy_file = tmp_path / "stopped_sample.mp4"
        dummy_file.write_bytes(b"data" * 1000)

        # 원본 길이 5시간(18000초), 1080p 메타데이터
        card.vod_info = VodInfo(
            video_no="999",
            video_title="긴 방송",
            channel_name="스트리머",
            duration=18000,
            formats=[VodFormatInfo(format_id="1080p", resolution="1080p", tbr=6000.0)],
        )
        # 구간 10분 = 600초 (0초 ~ 600초)
        card.section_popup.set_section_range(0.0, 600.0)

        card.set_task_status(TaskStatus.DOWNLOADING)
        # 20% 다운로드 진행 통지 (600초의 20% = 120초 = 02:00)
        progress = TaskProgress(
            task_id="t_stopped_dur",
            percentage=20.0,
            downloaded_bytes=1000,
            total_bytes=5000,
        )
        card.update_progress(progress)

        # 1. 중간 정지 상태로 전이: 3번 위치 시간 레이블 검증
        card.set_task_status(TaskStatus.STOPPED)
        assert card.status == TaskStatus.STOPPED
        # 18000초의 20%(3600초=01:00:00)가 아니라, 구간 600초의 20%(120초=02:00)가 표시되어야 함
        assert card.time_metric_label.text() == "02:00"

        # 2. 정지 상태에서 '작업 완료' 확정 호출: 목표 전체(10:00)로 덮어쓰지 않고 실제 받아진 02:00 유지 검증
        card.set_completed(str(dummy_file))
        assert card.status == TaskStatus.COMPLETED
        assert card.time_metric_label.text() == "02:00"

    def test_section_popup_get_section_range_handles_incomplete_input_safely(
        self, qtbot
    ) -> None:
        """사용자가 '00:' 등 불완전한 타임스탬프를 타이핑 중일 때 get_section_range가 예외 없이 안전하게 (None, None)을 반환하는지 검증."""
        from chzzk_downloader.gui.section_popup import SectionPopup

        popup = SectionPopup()
        qtbot.addWidget(popup)

        # 시작 체크 후 불완전 입력
        popup.start_check.setChecked(True)
        popup.start_edit.setText("00:")
        # 종료 체크 후 불완전 입력
        popup.end_check.setChecked(True)
        popup.end_edit.setText("::")

        # 크래시 없이 (None, None) 반환 단언
        s_start, s_end = popup.get_section_range()
        assert s_start is None
        assert s_end is None

    def test_subprocess_tracker_captures_ytdlp_utils_popen(self) -> None:
        """_SubprocessTracker가 yt_dlp.utils.Popen 및 external.Popen 인스턴스를 정확히 가로채 추적 풀에 등록하는지 검증."""
        import sys

        import yt_dlp.utils

        from chzzk_downloader.gui.workers import _SubprocessTracker

        tracked: set = set()
        with _SubprocessTracker(tracked):
            # yt-dlp의 실제 Popen 클래스를 사용해 더미 서브프로세스 기동 (크로스 플랫폼 지원)
            proc = yt_dlp.utils.Popen([sys.executable, "-c", "pass"])
            proc.wait()

        assert len(tracked) == 1
        assert proc in tracked

    def test_section_popup_reset_clears_selection_and_inputs(self, qtbot) -> None:
        """SectionPopup.reset() 호출 시 체크박스가 해제되고 입력창이 00:00:00으로 복원되는지 검증."""
        from chzzk_downloader.gui.section_popup import SectionPopup

        popup = SectionPopup()
        qtbot.addWidget(popup)

        popup.start_check.setChecked(True)
        popup.start_edit.setText("00:10:00")
        popup.end_check.setChecked(True)
        popup.end_edit.setText("00:20:00")

        popup.reset()

        assert not popup.start_check.isChecked()
        assert not popup.end_check.isChecked()
        assert popup.start_edit.text() == "00:00:00"
        assert popup.end_edit.text() == "00:00:00"
        assert popup.get_section_range() == (None, None)

    def test_task_card_hides_section_popup_when_download_starts(
        self, qtbot, monkeypatch
    ) -> None:
        """다운로드 시작 트리거 시 열려있던 section_popup이 자동으로 닫히는지 검증."""
        from chzzk_downloader.gui.task_card import TaskCardWidget

        monkeypatch.setattr(
            "chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available",
            lambda auto_download=False: True,
        )

        card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/12345")
        qtbot.addWidget(card)
        card.show()
        card.section_popup.show()
        assert card.section_popup.isVisible() is True

        card.trigger_start_download()
        assert card.section_popup.isVisible() is False

    def test_generate_vod_filename_prevents_inverted_section_range_when_duration_is_zero(
        self,
    ) -> None:
        """영상 길이가 0일 때 시작 시간만 설정된 경우 종료 시간이 시작 시간보다 작아지는 파일명 역전을 방지하는지 검증."""
        from chzzk_downloader.core.filename_generator import generate_vod_filename
        from chzzk_downloader.core.ytdlp import VodInfo

        info = VodInfo(
            video_no="12345",
            video_title="테스트 영상",
            channel_name="스트리머",
            duration=0,
        )
        fname = generate_vod_filename(
            info, ext="mp4", section_start=10.0, section_end=None
        )
        # 역전되어 [00_00_10-00_00_00]이 되지 않고 [00_00_10-end] 접미사로 안전 처리됨
        assert "[00_00_10-end]" in fname
        assert "[00_00_10-00_00_00]" not in fname

    def test_vod_completed_displays_section_duration_not_elapsed_time(
        self, qtbot: Any, tmp_path: Path
    ) -> None:
        """구간 다운로드 완료 시 이전 중지 경과시간 잔류나 팝업 리셋과 무관하게 유효 구간 길이(05:23)가 표시되는지 검증."""
        from chzzk_downloader.core.task_models import TaskProgress, TaskStatus
        from chzzk_downloader.core.ytdlp import VodInfo
        from chzzk_downloader.gui.task_card import TaskCardWidget

        card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/12345")
        qtbot.addWidget(card)

        # 전체 10분(600초) 영상 중 5분 23초(323초) 구간 설정 (00:00:00 ~ 00:05:23)
        info = VodInfo(
            video_no="12345",
            video_title="구간 테스트",
            channel_name="스트리머",
            duration=600,
        )
        card.update_with_vod_info(info)
        card.section_popup.set_section_range(0.0, 323.0)

        # 이전에 다운로드 중지되어 경과 시간 잔류 상태를 모의
        card.set_task_status(TaskStatus.STOPPED)

        # 새 다운로드 시작 트리거 (잔류 문자열이 리셋되고 적용 구간이 고정되어야 함)
        card.trigger_start_download()
        card.set_task_status(TaskStatus.DOWNLOADING)

        # 다운로드 도중 35초 경과 progress 수신 (elapsed_seconds=35.0)
        prog = TaskProgress(
            task_id=card.task_id,
            downloaded_bytes=10 * 1024 * 1024,
            total_bytes=50 * 1024 * 1024,
            percentage=20.0,
            elapsed_seconds=35.0,
        )
        card.update_progress(prog)

        # 다운로드 도중 또는 완료 시점에 팝업이 외부 동작으로 리셋되더라도 카드는 적용된 구간을 기억해야 함
        card.section_popup.reset()

        # 임의의 완료 파일 생성
        dest_file = tmp_path / "section_test.mp4"
        dest_file.write_bytes(b"dummy video data")

        # 다운로드 완료 및 확정
        card.set_completed(dest_file)
        card.set_task_status(TaskStatus.COMPLETED)

        # 3번 위치 라벨은 경과 시간("00:35" / "00:00:35")이나 전체 영상 길이("10:00")가 아니라 구간 길이("05:23")여야 함
        time_text = card.time_metric_label.text().strip()
        assert time_text != "00:35", "잔류 경과 시간 00:35가 완료 카드에 남아있음"
        assert time_text != "00:00:35", "경과 시간 00:00:35가 완료 카드에 남아있음"
        assert time_text != "10:00", "팝업 리셋으로 인해 원본 전체 길이가 표시됨"
        assert time_text == "05:23", f"예상 구간 길이 05:23 대신 {time_text}가 표시됨"

    def test_stopped_task_probes_actual_media_duration_and_size(
        self, qtbot: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """다운로드 정지 및 완료 확정 시 단순 추정식이 아닌 실제 미디어 프로빙 결과가 반영되는지 검증."""
        from chzzk_downloader.core.task_models import TaskProgress, TaskStatus
        from chzzk_downloader.core.ytdlp import VodInfo
        from chzzk_downloader.gui.task_card import TaskCardWidget

        # 100초 전체 영상에서 38% 진행 후 중지 시뮬레이션
        card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/12345")
        qtbot.addWidget(card)

        info = VodInfo(
            video_no="12345",
            video_title="중지 테스트 영상",
            channel_name="스트리머",
            duration=100,
        )
        card.update_with_vod_info(info)
        card.trigger_start_download()
        card.set_task_status(TaskStatus.DOWNLOADING)

        # 진행률 38% (단순 계산 시 38초 -> 00:38)
        prog = TaskProgress(
            task_id=card.task_id,
            downloaded_bytes=30_500_000,
            total_bytes=100_000_000,
            percentage=38.0,
            elapsed_seconds=20.0,
        )
        card.update_progress(prog)

        # 실제 디스크 파일 (40.9 MB, 실제 재생 시간은 32초, MP4 ftyp 매직 넘버 포함)
        test_media = tmp_path / "stopped_sample.mp4"
        test_media.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"x" * (42_912_771 - 12))
        card.target_path = test_media

        # probe_media_file 모킹: 실제 영상 길이는 32초, 크기는 42,912,771 바이트 반환
        from chzzk_downloader.core import ffmpeg_manager

        monkeypatch.setattr(
            ffmpeg_manager,
            "probe_media_file",
            lambda path: {
                "duration": 32.0,
                "size": 42_912_771,
                "width": 1920,
                "height": 1080,
            },
        )

        # STOPPED 상태로 진입
        card.set_task_status(TaskStatus.STOPPED)

        # 프로빙 워커가 비동기로 동작하여 카드 메트릭을 갱신할 때까지 대기
        qtbot.waitUntil(
            lambda: card.time_metric_label.text().strip() == "00:32",
            timeout=2000,
        )
        assert card.time_metric_label.text().strip() == "00:32"
        assert "40.9 MB" in card.size_metric_label.text()

        # 정지 상태에서 작업 완료(✓) 확정 시에도 00:32와 40.9 MB가 유지되어야 함
        card.set_completed(test_media)
        card.set_task_status(TaskStatus.COMPLETED)
        assert card.time_metric_label.text().strip() == "00:32"
        assert "40.9 MB" in card.size_metric_label.text()

        # 워커 안전 종료 정리
        card.close()

    def test_media_probe_worker_emits_probed_metadata(
        self, qtbot: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """MediaProbeWorker가 비동기 스레드에서 실제 미디어 duration과 size를 프로빙하고 시그널을 방출하는지 검증."""
        from chzzk_downloader.core import ffmpeg_manager
        from chzzk_downloader.gui.workers import MediaProbeWorker

        fake_file = tmp_path / "probe_test.mp4"
        fake_file.write_bytes(b"test data")

        monkeypatch.setattr(
            ffmpeg_manager,
            "probe_media_file",
            lambda path: {"duration": 45.5, "size": 1234567},
        )

        worker = MediaProbeWorker("task-123", fake_file)
        with qtbot.waitSignal(worker.probed, timeout=2000) as blocker:
            worker.start()

        task_id, duration, size = blocker.args
        assert task_id == "task-123"
        assert duration == 45.5
        assert size == 1234567

    def test_card_close_safely_detaches_media_probe_worker_without_blocking(
        self, qtbot: Any, tmp_path: Path
    ) -> None:
        """카드 종료 시 실행 중인 MediaProbeWorker가 terminate/wait 블로킹 없이 분리 보관되고 정상 정리되는지 검증."""
        import threading

        from chzzk_downloader.gui.task_card import (
            _DETACHED_PROBE_WORKERS,
            TaskCardWidget,
        )
        from chzzk_downloader.gui.workers import MediaProbeWorker

        fake_file = tmp_path / "probe_test.mp4"
        fake_file.write_bytes(b"test data")

        card = TaskCardWidget("https://chzzk.naver.com/video/v_probe_detach")
        qtbot.addWidget(card)

        release_event = threading.Event()

        class SlowProbeWorker(MediaProbeWorker):
            def run(self) -> None:
                release_event.wait(timeout=2.0)
                super().run()

        worker = SlowProbeWorker("task-probe-test", fake_file)
        card.attach_probe_worker(worker)

        callback_called = False

        def _spy_on_media_probed(*args: Any) -> None:
            nonlocal callback_called
            callback_called = True

        worker.probed.connect(_spy_on_media_probed)
        worker.start()

        import time

        qtbot.waitUntil(lambda: worker.isRunning(), timeout=1000)

        # 카드 닫기 (메인 스레드 블로킹 없이 즉시 반환)
        start_time = time.monotonic()
        card.close()
        elapsed = time.monotonic() - start_time
        assert elapsed < 0.2, (
            f"close() 호출 시 UI 스레드가 {elapsed:.2f}초 동안 동기 블로킹되었습니다."
        )

        # 분리 보관 집합에 등록되었는지 확인
        assert worker in _DETACHED_PROBE_WORKERS

        # 워커 재개 및 자연 종료 유도
        release_event.set()

        # 워커 종료 후 보관 집합에서 안전하게 해제되는지 확인
        qtbot.waitUntil(
            lambda: worker not in _DETACHED_PROBE_WORKERS,
            timeout=3000,
        )

        # 닫힌 카드의 콜백은 시그널 해제로 인해 실행되지 않아야 함
        assert not callback_called

    def test_subprocess_tracker_thread_isolation(self) -> None:
        """다중 스레드 동시 실행 시 _SubprocessTracker가 서로의 Popen 추적을 간섭하거나 유실하지 않는지 검증."""
        import subprocess
        import sys
        import threading

        from chzzk_downloader.gui.workers import _SubprocessTracker

        set_a: set = set()
        set_b: set = set()

        thread_b_started = threading.Event()
        thread_a_done = threading.Event()
        proc_b_ref: list[Any] = []

        def run_thread_a() -> None:
            with _SubprocessTracker(set_a):
                thread_b_started.wait(timeout=2.0)
                # Thread A 먼저 정상 탈출

        def run_thread_b() -> None:
            with _SubprocessTracker(set_b):
                thread_b_started.set()
                thread_a_done.wait(timeout=2.0)
                # Thread A가 나간 후 Thread B에서 프로세스 기동
                proc = subprocess.Popen([sys.executable, "-c", "pass"])
                proc.wait()
                proc_b_ref.append(proc)

        t_a = threading.Thread(target=run_thread_a)
        t_b = threading.Thread(target=run_thread_b)

        t_a.start()
        t_b.start()
        t_a.join(timeout=3.0)
        thread_a_done.set()
        t_b.join(timeout=3.0)

        assert len(proc_b_ref) == 1
        proc_b = proc_b_ref[0]
        assert proc_b in set_b, (
            "Thread A 퇴출로 인해 Thread B의 서브프로세스 추적이 유실되었습니다."
        )
        assert proc_b not in set_a, (
            "Thread B의 서브프로세스가 Thread A에 잘못 오염 등록되었습니다."
        )

    def test_reset_for_redownload_detaches_previous_probe_worker(
        self, qtbot: Any, tmp_path: Path
    ) -> None:
        """재다운로드 리셋 시 실행 중인 이전 프로빙 워커가 안전하게 분리되고 UI를 오염시키지 않는지 검증."""
        import threading

        from chzzk_downloader.gui.task_card import (
            _DETACHED_PROBE_WORKERS,
            TaskCardWidget,
        )
        from chzzk_downloader.gui.workers import MediaProbeWorker

        fake_file = tmp_path / "probe_reuse.mp4"
        fake_file.write_bytes(b"data" * 512)

        card = TaskCardWidget("https://chzzk.naver.com/video/v_reuse")
        qtbot.addWidget(card)

        release_event = threading.Event()

        class SlowWorker(MediaProbeWorker):
            def run(self) -> None:
                release_event.wait(timeout=2.0)
                super().run()

        worker = SlowWorker("v_reuse", fake_file)
        card.attach_probe_worker(worker)
        worker.start()

        qtbot.waitUntil(lambda: worker.isRunning(), timeout=1000)

        # 재다운로드 승인으로 인한 카드 리셋
        card.reset_for_redownload()

        # 분리 보관 집합으로 위임되었는지 검증
        assert worker in _DETACHED_PROBE_WORKERS

        release_event.set()
        qtbot.waitUntil(
            lambda: worker not in _DETACHED_PROBE_WORKERS,
            timeout=3000,
        )

    def test_detach_probe_worker_handles_already_finished_thread(
        self, qtbot: Any, tmp_path: Path
    ) -> None:
        """워커가 이미 종료된 상태에서 detach 호출 시 _DETACHED_PROBE_WORKERS에 영구 고립되지 않는지 검증."""
        from chzzk_downloader.gui.task_card import (
            _DETACHED_PROBE_WORKERS,
            TaskCardWidget,
        )
        from chzzk_downloader.gui.workers import MediaProbeWorker

        fake_file = tmp_path / "probe_done.mp4"
        fake_file.write_bytes(b"data" * 512)

        card = TaskCardWidget("https://chzzk.naver.com/video/v_finished")
        qtbot.addWidget(card)

        worker = MediaProbeWorker("v_finished", fake_file)
        card.attach_probe_worker(worker)
        worker.start()
        qtbot.waitUntil(lambda: worker.isFinished(), timeout=2000)

        # 이미 종료된 상태에서 카드 닫기/분리 호출
        card.close()

        # 이미 끝난 워커는 분리 집합에 영구 잔존하지 않아야 함
        assert worker not in _DETACHED_PROBE_WORKERS

    def test_main_window_close_event_waits_for_detached_probe_workers(
        self, qtbot: Any, tmp_path: Path
    ) -> None:
        """메인 윈도우 종료 시 _DETACHED_PROBE_WORKERS에 잔류한 비동기 워커가 안전하게 대기 및 정리되는지 검증."""
        import threading

        from PyQt6.QtGui import QCloseEvent

        from chzzk_downloader.gui.main_window import MainWindow
        from chzzk_downloader.gui.task_card import _DETACHED_PROBE_WORKERS
        from chzzk_downloader.gui.workers import MediaProbeWorker

        win = MainWindow()
        qtbot.addWidget(win)

        fake_file = tmp_path / "probe_hang.mp4"
        fake_file.write_bytes(b"data" * 512)

        release = threading.Event()

        class HangWorker(MediaProbeWorker):
            def run(self) -> None:
                release.wait(timeout=2.0)
                super().run()

        worker = HangWorker("hang-task", fake_file)
        _DETACHED_PROBE_WORKERS.add(worker)
        worker.start()

        # 워커 재개 및 메인 윈도우 종료 이벤트 처리
        release.set()
        win.closeEvent(QCloseEvent())

        # closeEvent 종료 후 _DETACHED_PROBE_WORKERS가 비워지고 워커가 실행 중이 아니어야 함
        assert len(_DETACHED_PROBE_WORKERS) == 0
        assert not worker.isRunning()

    def test_subprocess_tracker_enforces_utf8_and_replace_on_text_pipes(
        self, monkeypatch: Any
    ) -> None:
        """_SubprocessTracker가 text 모드 Popen 호출 시 encoding='utf-8' 및 errors='replace'를 주입하는지 검증."""
        import subprocess

        from chzzk_downloader.gui.workers import _SubprocessTracker

        captured_kwargs: dict[str, Any] = {}

        class FakePopen:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                captured_kwargs.update(kwargs)

        monkeypatch.setattr(subprocess, "Popen", FakePopen)

        import sys

        tracked: set[Any] = set()
        with _SubprocessTracker(tracked):
            subprocess.Popen([sys.executable, "-c", "pass"], text=True)

        assert captured_kwargs.get("encoding") == "utf-8"
        assert captured_kwargs.get("errors") == "replace"

    def test_section_time_spinbox_structure_and_arrow_keys(self, qtbot: Any) -> None:
        """SectionPopup의 시간 입력 위젯이 시/분/초 분할 스핀박스와 상하 화살표 증감을 지원하는지 검증."""
        from PyQt6.QtCore import Qt

        from chzzk_downloader.gui.section_popup import SectionPopup

        popup = SectionPopup()
        qtbot.addWidget(popup)

        # 시작 시간 위젯이 hour, min, sec 스핀박스를 보유하고 있는지 확인
        time_widget = popup.start_edit
        assert hasattr(time_widget, "hour_spin")
        assert hasattr(time_widget, "min_spin")
        assert hasattr(time_widget, "sec_spin")

        # 초기 값 검증
        popup.start_check.setChecked(True)
        time_widget.setText("01:02:03.00")
        assert time_widget.hour_spin.value() == 1
        assert time_widget.min_spin.value() == 2
        assert abs(time_widget.sec_spin.value() - 3.0) < 0.01

        # 위쪽 방향키(Up) 입력 시 초 스핀박스 값 1 증가 검증
        qtbot.keyClick(time_widget.sec_spin, Qt.Key.Key_Up)
        assert abs(time_widget.sec_spin.value() - 4.0) < 0.01

    def test_section_download_in_downloading_state_hides_stop_button(
        self, qtbot: Any, monkeypatch: Any
    ) -> None:
        """구간 다운로드 진행 중(DOWNLOADING)일 때 4번 위치의 정지 버튼(stop_btn)이 숨김 처리되는지 검증."""
        from chzzk_downloader.core.task_models import TaskStatus
        from chzzk_downloader.gui.task_card import TaskCardWidget

        monkeypatch.setattr(
            "chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available",
            lambda auto_download=False: True,
        )

        card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/12345")
        qtbot.addWidget(card)
        card.show()

        # 1. 일반 다운로드 상태 전이 시에는 stop_btn이 보여야 함
        card.set_task_status(TaskStatus.DOWNLOADING)
        assert card.stop_btn.isVisible() is True

        # 2. 구간이 적용된 다운로드 카드 생성 및 상태 전이 시 stop_btn이 숨겨져야 함 (방안 A)
        section_card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/12345")
        qtbot.addWidget(section_card)
        section_card.show()
        section_card.section_popup.set_section_range(10.0, 60.0)
        section_card.set_task_status(TaskStatus.DOWNLOADING)
        assert section_card.stop_btn.isVisible() is False

    def test_media_remux_worker_finalizes_media_safely(
        self, qtbot: Any, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """MediaRemuxWorker가 비동기 스레드에서 무손실 리먹싱을 정상 수행하고 성공 시그널을 방출하는지 검증."""
        from chzzk_downloader.core import ffmpeg_manager
        from chzzk_downloader.gui.media_workers import MediaRemuxWorker

        fake_src = tmp_path / "partial.mp4"
        fake_src.write_bytes(b"partial video data")
        fake_dst = tmp_path / "final.mp4"

        monkeypatch.setattr(
            ffmpeg_manager,
            "remux_media_file",
            lambda src, dst: True,
        )

        worker = MediaRemuxWorker("task-999", fake_src, fake_dst)
        with qtbot.waitSignal(worker.remux_finished, timeout=2000) as blocker:
            worker.start()

        task_id, success, out_path = blocker.args
        assert task_id == "task-999"
        assert success is True
        assert out_path == str(fake_dst)
