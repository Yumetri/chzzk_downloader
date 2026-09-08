"""T0110. FFmpeg 상태 확인 및 호환성 검증 단위 및 통합 테스트."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from chzzk_downloader.config import DEFAULT_FFMPEG_BINARY_NAME
from chzzk_downloader.core.ffmpeg_manager import (
    FFmpegProbeResult,
    FFmpegStatus,
    clear_probe_cache,
    get_candidate_ffmpeg_paths,
    get_candidate_ffprobe_paths,
    get_ffmpeg_compatible_args,
    get_ffmpeg_path,
    get_ffprobe_path,
    is_ffmpeg_available,
    is_ffprobe_available,
    probe_ffmpeg,
    probe_ffprobe,
    probe_media_file,
    resolve_ffmpeg_path,
    resolve_ffprobe_path,
    verify_media_file_integrity,
)
from chzzk_downloader.core.settings_manager import (
    get_current_settings,
    load_settings,
    set_custom_settings_path,
    update_current_settings,
)
from chzzk_downloader.core.ytdlp import VodInfo
from chzzk_downloader.gui.settings_window import SettingsWindow
from chzzk_downloader.gui.task_card import TaskCardWidget, TaskStatus


@pytest.fixture(autouse=True)
def cleanup_ffmpeg_cache():
    """모든 테스트 전후로 프로빙 캐시를 초기화합니다."""
    clear_probe_cache()
    yield
    clear_probe_cache()


@pytest.fixture
def test_settings_env(tmp_path):
    """임시 디렉터리의 settings.json 경로를 사용하도록 격리하는 fixture."""
    test_settings_file = tmp_path / "test_settings.json"
    set_custom_settings_path(test_settings_file)
    yield test_settings_file
    set_custom_settings_path(None)


def test_ffmpeg_probe_success_with_version_and_compatibility(tmp_path):
    """최신 FFmpeg(v6.1+) 바이너리 실행, 버전 파싱 및 치지직 호환 인자 프로빙 검증."""
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.write_text("binary", encoding="utf-8")

    def mock_subprocess_run(cmd, *args, **kwargs):
        if "-version" in cmd:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=(
                    "ffmpeg version 6.1.1 Copyright (c) 2000-2023 the FFmpeg developers\n"
                    "built with gcc 13.2.0\n"
                ),
                stderr="",
            )
        if "-h" in cmd and "demuxer=hls" in cmd:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=(
                    "HLS demuxer AVOptions:\n"
                    "  -allowed_extensions <string>\n"
                    "  -extension_picky <boolean>\n"
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        result = probe_ffmpeg(fake_ffmpeg)

        assert result.status == FFmpegStatus.AVAILABLE
        assert result.version == "6.1.1"
        assert result.path == fake_ffmpeg.resolve()
        assert result.supports_extension_picky is True
        assert result.supports_allowed_extensions is True
        assert result.compatible_args == [
            "-extension_picky",
            "0",
            "-allowed_extensions",
            "ALL",
        ]
        assert "사용 가능 (FFmpeg 6.1.1 · 치지직 호환)" in result.display_text


def test_ffmpeg_probe_older_version_without_picky(tmp_path):
    """구버전 FFmpeg(v6.0 등)에서 allowed_extensions만 지원할 때의 동작 검증."""
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.write_text("binary", encoding="utf-8")

    def mock_subprocess_run(cmd, *args, **kwargs):
        if "-version" in cmd:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=(
                    "ffmpeg version 6.0-essentials_build-www.gyan.dev Copyright (c) 2000-2023\n"
                ),
                stderr="",
            )
        if "-h" in cmd and "demuxer=hls" in cmd:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="HLS demuxer AVOptions:\n  -allowed_extensions <string>\n",
                stderr="",
            )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        result = probe_ffmpeg(fake_ffmpeg)

        assert result.status == FFmpegStatus.AVAILABLE
        assert result.version == "6.0-essentials_build-www.gyan.dev"
        assert result.supports_extension_picky is False
        assert result.supports_allowed_extensions is True
        assert result.compatible_args == ["-allowed_extensions", "ALL"]
        assert (
            result.display_text
            == "사용 가능 (FFmpeg 6.0-essentials_build-www.gyan.dev)"
        )


def test_ffmpeg_probe_file_not_found(tmp_path):
    """존재하지 않는 파일 경로가 주어졌을 때 파일 없음(NOT_FOUND) 상태 분류 검증."""
    non_existent = tmp_path / "no_ffmpeg.exe"
    result = probe_ffmpeg(non_existent)

    assert result.status == FFmpegStatus.NOT_FOUND
    assert result.display_text == "파일 없음"
    assert "존재하지 않습니다" in result.error_message


def test_ffmpeg_probe_execution_failure_non_zero_exit(tmp_path):
    """실행 시 비정상 종료 코드(0이 아님)를 반환할 때 실행 실패(EXECUTION_FAILED) 분류 검증."""
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.write_text("binary", encoding="utf-8")

    with patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["ffmpeg", "-version"], returncode=1, stdout="", stderr="Error"
        ),
    ):
        result = probe_ffmpeg(fake_ffmpeg)

        assert result.status == FFmpegStatus.EXECUTION_FAILED
        assert result.display_text == "실행 실패"
        assert "비정상 종료 코드" in result.error_message


def test_ffmpeg_probe_execution_failure_not_ffmpeg(tmp_path):
    """실행은 성공했으나 FFmpeg가 아닌 다른 바이너리(예: python.exe 등)일 때 거부 검증."""
    fake_binary = tmp_path / "other.exe"
    fake_binary.write_text("binary", encoding="utf-8")

    with patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["other.exe", "-version"],
            returncode=0,
            stdout="Python 3.12.0 (tags/v3.12.0:0fb18b0)\n",
            stderr="",
        ),
    ):
        result = probe_ffmpeg(fake_binary)

        assert result.status == FFmpegStatus.EXECUTION_FAILED
        assert result.display_text == "실행 실패"
        assert "FFmpeg 바이너리가 아님" in result.error_message


def test_ffmpeg_probe_timeout(tmp_path):
    """프로세스 실행 후 타임아웃 발생 시 응답 없음(TIMEOUT) 상태 분류 검증."""
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.write_text("binary", encoding="utf-8")

    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg", "-version"], timeout=3.0),
    ):
        result = probe_ffmpeg(fake_ffmpeg)

        assert result.status == FFmpegStatus.TIMEOUT
        assert result.display_text == "응답 없음"
        assert "실행 시간 초과" in result.error_message


def test_candidate_paths_fallback_hierarchy(tmp_path, monkeypatch):
    """내장 번들, %TEMP%, bin 디렉터리, 시스템 PATH 우선순위 탐색 검증."""
    # 1. 윈도우 %TEMP% 경로 후보 포함 확인
    monkeypatch.setenv("TEMP", str(tmp_path))
    candidates = get_candidate_ffmpeg_paths()
    expected_temp_ffmpeg = tmp_path / DEFAULT_FFMPEG_BINARY_NAME
    assert any(c.resolve() == expected_temp_ffmpeg.resolve() for c in candidates)

    # 2. %TEMP%\ffmpeg.exe가 실제로 존재할 때 resolve_ffmpeg_path가 찾아내는지 확인
    expected_temp_ffmpeg.write_text("dummy", encoding="utf-8")
    resolved = resolve_ffmpeg_path()
    assert resolved is not None
    assert resolved.resolve() == expected_temp_ffmpeg.resolve()


def test_is_ffmpeg_available_and_compatible_args(tmp_path):
    """is_ffmpeg_available() 및 get_ffmpeg_compatible_args() 인터페이스 및 캐싱 검증."""
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.write_text("binary", encoding="utf-8")

    mock_result = FFmpegProbeResult(
        status=FFmpegStatus.AVAILABLE,
        path=fake_ffmpeg,
        version="6.1.1",
        supports_extension_picky=True,
        supports_allowed_extensions=True,
        compatible_args=["-extension_picky", "0", "-allowed_extensions", "ALL"],
    )

    with patch(
        "chzzk_downloader.core.ffmpeg_manager.probe_ffmpeg", return_value=mock_result
    ):
        assert is_ffmpeg_available() is True
        assert get_ffmpeg_path() == fake_ffmpeg
        assert get_ffmpeg_compatible_args() == [
            "-extension_picky",
            "0",
            "-allowed_extensions",
            "ALL",
        ]

    # 가용하지 않은 상태 모킹
    clear_probe_cache()
    mock_unavailable = FFmpegProbeResult(status=FFmpegStatus.NOT_FOUND)
    with patch(
        "chzzk_downloader.core.ffmpeg_manager.probe_ffmpeg",
        return_value=mock_unavailable,
    ):
        assert is_ffmpeg_available(force_recheck=True) is False
        assert get_ffmpeg_path() is None


def test_settings_save_and_reload_ffmpeg_path(test_settings_env, tmp_path):
    """settings.json에 FFmpeg 경로 저장 및 앱 재실행 복원 검증."""
    custom_ffmpeg = tmp_path / "custom" / "ffmpeg.exe"
    custom_ffmpeg.parent.mkdir(parents=True)
    custom_ffmpeg.write_text("binary", encoding="utf-8")

    ok, msg = update_current_settings(ffmpeg_path=custom_ffmpeg)
    assert ok is True
    assert get_current_settings().ffmpeg_path == str(custom_ffmpeg)

    reloaded = load_settings(test_settings_env)
    assert reloaded.ffmpeg_path == str(custom_ffmpeg)

    # 초기화 (빈 문자열)
    ok2, _ = update_current_settings(ffmpeg_path="")
    assert ok2 is True
    assert get_current_settings().ffmpeg_path == ""


def test_settings_window_clean_without_ffmpeg_widget(qtbot, test_settings_env):
    """SettingsWindow가 불필요한 FFmpeg 수동 설정 위젯 없이 깔끔하게 일반/쿠키만 구성되는지 검증."""
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()

    # FFmpeg 수동 설정 위젯은 제거되어 존재하지 않음 (Zero-Config 자동 관리)
    assert not hasattr(window, "ffmpeg_group")
    assert not hasattr(window, "ffmpeg_status_label")
    assert not hasattr(window, "ffmpeg_browse_btn")

    # 일반 설정 및 쿠키 관리 그룹만 유지
    assert hasattr(window, "general_group")
    assert hasattr(window, "cookie_group")


def test_download_blocked_when_ffmpeg_unavailable(qtbot):
    """FFmpeg가 사용 불가능할 때 다운로드가 차단되고 카드 상태가 유지되는지 검증."""
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

    # FFmpeg 가용 상태 모킹
    with patch(
        "chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available", return_value=True
    ):
        started2 = card.trigger_start_download()
        assert started2 is True
        assert card.status == TaskStatus.DOWNLOADING


# ==============================================================================
# FFprobe 추가 진단 및 미디어 파일 무결성 검증 테스트
# ==============================================================================


def test_ffprobe_probe_success(tmp_path):
    """FFprobe 바이너리 실행 및 버전 파싱 정상 동작 검증."""
    fake_ffprobe = tmp_path / "ffprobe.exe"
    fake_ffprobe.write_text("binary", encoding="utf-8")

    mock_proc = subprocess.CompletedProcess(
        args=[str(fake_ffprobe), "-version"],
        returncode=0,
        stdout="ffprobe version 6.0-essentials_build-www.gyan.dev Copyright (c) 2007-2023\n",
        stderr="",
    )

    with patch("subprocess.run", return_value=mock_proc):
        result = probe_ffprobe(fake_ffprobe)
        assert result.status == FFmpegStatus.AVAILABLE
        assert result.version == "6.0-essentials_build-www.gyan.dev"
        assert result.path == fake_ffprobe.resolve()


def test_ffprobe_probe_not_found_and_failure(tmp_path):
    """FFprobe 파일 미존재, 타임아웃, 비정상 종료 예외 처리 검증."""
    # 1. 파일 없음
    non_existent = tmp_path / "missing_ffprobe.exe"
    res1 = probe_ffprobe(non_existent)
    assert res1.status == FFmpegStatus.NOT_FOUND

    # 2. 타임아웃
    fake_bin = tmp_path / "ffprobe.exe"
    fake_bin.write_text("binary", encoding="utf-8")
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=3.0),
    ):
        res2 = probe_ffprobe(fake_bin)
        assert res2.status == FFmpegStatus.TIMEOUT

    # 3. 비정상 종료
    fail_proc = subprocess.CompletedProcess(
        args=["ffprobe"], returncode=1, stdout="", stderr="Error"
    )
    with patch("subprocess.run", return_value=fail_proc):
        res3 = probe_ffprobe(fake_bin)
        assert res3.status == FFmpegStatus.EXECUTION_FAILED

    # 4. 버전 파싱 실패
    bad_proc = subprocess.CompletedProcess(
        args=["ffprobe"], returncode=0, stdout="not ffprobe", stderr=""
    )
    with patch("subprocess.run", return_value=bad_proc):
        res4 = probe_ffprobe(fake_bin)
        assert res4.status == FFmpegStatus.EXECUTION_FAILED


def test_candidate_ffprobe_paths_and_resolve(tmp_path, test_settings_env):
    """FFprobe 탐색 경로 우선순위 및 resolve_ffprobe_path 검증."""
    custom_ffprobe = tmp_path / "custom_bin" / "ffprobe.exe"
    custom_ffprobe.parent.mkdir(parents=True, exist_ok=True)
    custom_ffprobe.write_text("custom", encoding="utf-8")

    # 설정에 사용자 경로 지정
    update_current_settings(ffprobe_path=str(custom_ffprobe))

    candidates = get_candidate_ffprobe_paths()
    assert candidates[0] == custom_ffprobe

    resolved = resolve_ffprobe_path()
    assert resolved == custom_ffprobe.resolve()


def test_is_ffprobe_available_and_caching(tmp_path):
    """is_ffprobe_available 캐싱 및 get_ffprobe_path 정상 반환 검증."""
    fake_bin = tmp_path / "ffprobe.exe"
    fake_bin.write_text("bin", encoding="utf-8")

    probe_ok = FFmpegProbeResult(
        status=FFmpegStatus.AVAILABLE,
        path=fake_bin,
        version="6.0",
    )

    with patch(
        "chzzk_downloader.core.ffmpeg_manager.probe_ffprobe", return_value=probe_ok
    ) as mock_probe:
        assert is_ffprobe_available() is True
        assert get_ffprobe_path() == fake_bin
        # 캐싱되어 1회만 호출됨
        assert is_ffprobe_available() is True
        assert mock_probe.call_count == 1

        clear_probe_cache()
        assert is_ffprobe_available(force_recheck=True) is True
        assert mock_probe.call_count == 2


def test_probe_media_file_and_verify_integrity(tmp_path):
    """probe_media_file 및 verify_media_file_integrity 스트림 검증 로직 테스트."""
    video_file = tmp_path / "output.mp4"
    video_file.write_text("fake video content", encoding="utf-8")

    fake_json_output = (
        "{\n"
        '  "streams": [\n'
        '    {"index": 0, "codec_type": "video", "codec_name": "h264", "duration": "120.0"},\n'
        '    {"index": 1, "codec_type": "audio", "codec_name": "aac", "duration": "120.0"}\n'
        "  ],\n"
        '  "format": {"duration": "120.0", "size": "1048576"}\n'
        "}"
    )

    mock_proc = subprocess.CompletedProcess(
        args=["ffprobe"],
        returncode=0,
        stdout=fake_json_output,
        stderr="",
    )

    with patch(
        "chzzk_downloader.core.ffmpeg_manager.get_ffprobe_path",
        return_value=tmp_path / "ffprobe.exe",
    ):
        with patch("subprocess.run", return_value=mock_proc):
            # 1. 정상 미디어 프로빙
            info = probe_media_file(video_file)
            assert info is not None
            assert len(info["streams"]) == 2

            # 2. 무결성 검증 성공
            ok, msg = verify_media_file_integrity(video_file)
            assert ok is True
            assert "검증 완료" in msg

    # 3. 0바이트 파일 실패 검증
    empty_file = tmp_path / "empty.mp4"
    empty_file.touch()
    ok_empty, msg_empty = verify_media_file_integrity(empty_file)
    assert ok_empty is False
    assert "0바이트" in msg_empty

    # 4. 존재하지 않는 파일 검증
    missing_file = tmp_path / "missing.mp4"
    ok_missing, msg_missing = verify_media_file_integrity(missing_file)
    assert ok_missing is False
    assert "존재하지 않습니다" in msg_missing
