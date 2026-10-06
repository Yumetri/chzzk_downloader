"""FFmpeg/FFprobe 가용성 진단, 버전 및 옵션 파싱, 6단계 수명주기 및 미디어 무결성 검증 단위 테스트."""

from __future__ import annotations

import concurrent.futures
import inspect
import io
import subprocess
import sys
import time
import tracemalloc
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from chzzk_downloader.config import (
    DEFAULT_FFMPEG_BINARY_NAME,
)
from chzzk_downloader.core.ffmpeg_manager import (
    FFmpegProbeResult,
    FFmpegStatus,
    clear_probe_cache,
    download_ffmpeg_binary,
    ensure_ffmpeg_available,
    get_candidate_ffmpeg_paths,
    get_candidate_ffprobe_paths,
    get_default_ffmpeg_install_dir,
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
    update_current_settings,
)
from chzzk_downloader.core.ytdlp import VodInfo
from chzzk_downloader.gui.task_card import TaskCardWidget, TaskStatus


@pytest.fixture
def clean_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """외부 환경(PATH, TEMP, _MEIPASS)을 격리하는 fixture."""
    # 1. settings 초기화
    update_current_settings(
        download_dir=str(tmp_path / "downloads"),
        ffmpeg_path="",
        vod_auto_download=True,
    )

    # 2. _MEIPASS 제거
    if hasattr(sys, "_MEIPASS"):
        monkeypatch.delattr(sys, "_MEIPASS")

    # 3. TEMP / TMP 환경변수를 빈 임시 디렉터리로 격리
    empty_temp = tmp_path / "isolated_temp"
    empty_temp.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TEMP", str(empty_temp))
    monkeypatch.setenv("TMP", str(empty_temp))

    # 4. PATH 탐색(shutil.which) 기본 None 반환 격리
    monkeypatch.setattr("shutil.which", lambda cmd: None)

    # 5. 사용자 홈 디렉터리(~/.chzzk_downloader/bin) 격리
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    return tmp_path


def create_fake_card(qtbot) -> tuple[TaskCardWidget, list[str]]:
    """테스트용 TaskCardWidget 인스턴스를 생성하고 download_blocked 시그널을 수집합니다."""
    vod_info = VodInfo(
        video_no="998877",
        video_title="FFmpeg 6단계 라이프사이클 테스트",
        channel_name="스트리머테스트",
    )
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/998877",
        status=TaskStatus.READY,
        vod_info=vod_info,
    )
    qtbot.addWidget(card)

    blocked_reasons: list[str] = []
    card.download_blocked.connect(blocked_reasons.append)
    return card, blocked_reasons


def stub_subprocess_ffmpeg_probe(executable_path: Path):
    """지정된 바이너리 경로의 -version 실행 시 정상 FFmpeg 6.0 출력으로 응답하는 stub."""

    def mock_run(cmd, *args, **kwargs):
        cmd_str = [str(c) for c in cmd]
        if str(executable_path) in cmd_str[0] or cmd_str[0] == str(executable_path):
            if "-version" in cmd_str:
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout="ffmpeg version 6.0-essentials_build Copyright (c) 2000-2023\n",
                    stderr="",
                )
            if "-h" in cmd_str and "demuxer=hls" in cmd_str:
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout="HLS demuxer AVOptions:\n  -allowed_extensions <string>\n",
                    stderr="",
                )
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="", stderr="not found"
        )

    return mock_run


# ==============================================================================
# FFmpeg 기본 프로빙 단위 테스트
# ==============================================================================


@pytest.mark.ticket("T0110")
def test_ffmpeg_probe_success_with_version_and_compatibility(tmp_path: Path) -> None:
    """[T0110] 최신 FFmpeg(v6.1+) 바이너리 실행, 버전 파싱 및 치지직 호환 인자 프로빙 검증."""
    fake_ffmpeg = tmp_path / DEFAULT_FFMPEG_BINARY_NAME
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


@pytest.mark.ticket("T0110")
def test_ffmpeg_probe_older_version_without_picky(tmp_path: Path) -> None:
    """[T0110] 구버전 FFmpeg(v6.0 등)에서 allowed_extensions만 지원할 때의 동작 검증."""
    fake_ffmpeg = tmp_path / DEFAULT_FFMPEG_BINARY_NAME
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


@pytest.mark.ticket("T0110")
def test_ffmpeg_probe_file_not_found(tmp_path: Path) -> None:
    """[T0110] 존재하지 않는 파일 경로가 주어졌을 때 파일 없음(NOT_FOUND) 상태 분류 검증."""
    non_existent = tmp_path / "no_ffmpeg.exe"
    result = probe_ffmpeg(non_existent)

    assert result.status == FFmpegStatus.NOT_FOUND
    assert result.display_text == "파일 없음"
    assert "존재하지 않습니다" in result.error_message


@pytest.mark.ticket("T0110")
def test_ffmpeg_probe_execution_failure_non_zero_exit(tmp_path: Path) -> None:
    """[T0110] 실행 시 비정상 종료 코드(0이 아님)를 반환할 때 실행 실패(EXECUTION_FAILED) 분류 검증."""
    fake_ffmpeg = tmp_path / DEFAULT_FFMPEG_BINARY_NAME
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


@pytest.mark.ticket("T0110")
def test_ffmpeg_probe_execution_failure_not_ffmpeg(tmp_path: Path) -> None:
    """[T0110] 실행은 성공했으나 FFmpeg가 아닌 다른 바이너리(예: python.exe 등)일 때 거부 검증."""
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


@pytest.mark.ticket("T0110")
def test_ffmpeg_probe_timeout(tmp_path: Path) -> None:
    """[T0110] 프로세스 실행 후 타임아웃 발생 시 응답 없음(TIMEOUT) 상태 분류 검증."""
    fake_ffmpeg = tmp_path / DEFAULT_FFMPEG_BINARY_NAME
    fake_ffmpeg.write_text("binary", encoding="utf-8")

    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg", "-version"], timeout=3.0),
    ):
        result = probe_ffmpeg(fake_ffmpeg)

        assert result.status == FFmpegStatus.TIMEOUT
        assert result.display_text == "응답 없음"
        assert "실행 시간 초과" in result.error_message


@pytest.mark.ticket("T0110")
def test_candidate_paths_fallback_hierarchy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[T0110] 내장 번들, %TEMP%, bin 디렉터리, 시스템 PATH 우선순위 탐색 검증."""
    # 1. 윈도우 %TEMP% 경로 후보 포함 확인
    monkeypatch.setenv("TEMP", str(tmp_path))
    candidates = get_candidate_ffmpeg_paths()
    expected_temp_ffmpeg = tmp_path / DEFAULT_FFMPEG_BINARY_NAME
    assert any(c.resolve() == expected_temp_ffmpeg.resolve() for c in candidates)

    # 2. %TEMP% 경로가 실제로 존재할 때 resolve_ffmpeg_path가 찾아내는지 확인
    expected_temp_ffmpeg.write_text("dummy", encoding="utf-8")
    resolved = resolve_ffmpeg_path()
    assert resolved is not None
    assert resolved.resolve() == expected_temp_ffmpeg.resolve()


@pytest.mark.ticket("T0110")
def test_is_ffmpeg_available_and_compatible_args(tmp_path: Path) -> None:
    """[T0110] is_ffmpeg_available() 및 get_ffmpeg_compatible_args() 인터페이스 및 캐싱 검증."""
    fake_ffmpeg = tmp_path / DEFAULT_FFMPEG_BINARY_NAME
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


# ==============================================================================
# FFprobe 추가 진단 및 미디어 파일 무결성 검증 테스트
# ==============================================================================


@pytest.mark.ticket("T0110")
def test_ffprobe_probe_success(tmp_path: Path) -> None:
    """[T0110] FFprobe 바이너리 실행 및 버전 파싱 정상 동작 검증."""
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


@pytest.mark.ticket("T0110")
def test_ffprobe_probe_not_found_and_failure(tmp_path: Path) -> None:
    """[T0110] FFprobe 파일 미존재, 타임아웃, 비정상 종료 예외 처리 검증."""
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


@pytest.mark.ticket("T0110")
def test_candidate_ffprobe_paths_and_resolve(tmp_path: Path) -> None:
    """[T0110] FFprobe 탐색 경로 우선순위 및 resolve_ffprobe_path 검증."""
    custom_ffprobe = tmp_path / "custom_bin" / "ffprobe.exe"
    custom_ffprobe.parent.mkdir(parents=True, exist_ok=True)
    custom_ffprobe.write_text("custom", encoding="utf-8")

    update_current_settings(ffprobe_path=str(custom_ffprobe))

    candidates = get_candidate_ffprobe_paths()
    assert candidates[0] == custom_ffprobe

    resolved = resolve_ffprobe_path()
    assert resolved == custom_ffprobe.resolve()


@pytest.mark.ticket("T0110")
def test_is_ffprobe_available_and_caching(tmp_path: Path) -> None:
    """[T0110] is_ffprobe_available 캐싱 및 get_ffprobe_path 정상 반환 검증."""
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
        assert is_ffprobe_available() is True
        assert mock_probe.call_count == 1

        clear_probe_cache()
        assert is_ffprobe_available(force_recheck=True) is True
        assert mock_probe.call_count == 2


@pytest.mark.ticket("T0110")
def test_probe_media_file_and_verify_integrity(tmp_path: Path) -> None:
    """[T0110] probe_media_file 및 verify_media_file_integrity 매직 넘버 및 재생 시간 무결성 검증 테스트."""
    # 정상 MP4 ISO BMFF 헤더를 가진 모의 파일 생성 (ftyp 박스)
    video_file = tmp_path / "output.mp4"
    valid_mp4_header = (
        b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 100
    )
    video_file.write_bytes(valid_mp4_header)

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

            # 2. 무결성 검증 성공 (재생 시간 일치)
            ok, msg = verify_media_file_integrity(video_file, expected_duration=120.0)
            assert ok is True
            assert "검증 완료" in msg

            # 3. 기대 재생 시간과 불일치 시 실패 검증
            ok_diff, msg_diff = verify_media_file_integrity(
                video_file, expected_duration=60.0
            )
            assert ok_diff is False
            assert "초과합니다" in msg_diff

    # 4. 가짜 텍스트 파일(.mp4 확장자 위장) 매직 바이트 차단 검증
    fake_txt_video = tmp_path / "fake_text.mp4"
    fake_txt_video.write_text("fake video content that is plain text", encoding="utf-8")
    ok_txt, msg_txt = verify_media_file_integrity(fake_txt_video)
    assert ok_txt is False
    assert "컨테이너 헤더 검증 실패" in msg_txt

    # 5. 0바이트 파일 실패 검증
    empty_file = tmp_path / "empty.mp4"
    empty_file.touch()
    ok_empty, msg_empty = verify_media_file_integrity(empty_file)
    assert ok_empty is False
    assert "0바이트" in msg_empty

    # 6. 존재하지 않는 파일 검증
    missing_file = tmp_path / "missing.mp4"
    ok_missing, msg_missing = verify_media_file_integrity(missing_file)
    assert ok_missing is False
    assert "존재하지 않습니다" in msg_missing

    # 7. 재생 시간 0초(손상된 스트림) 실패 검증
    fake_zero_dur = '{"streams": [{"codec_type": "video", "duration": "0.0"}], "format": {"duration": "0.0"}}'
    mock_zero_proc = subprocess.CompletedProcess(
        args=["ffprobe"], returncode=0, stdout=fake_zero_dur, stderr=""
    )
    with patch(
        "chzzk_downloader.core.ffmpeg_manager.get_ffprobe_path",
        return_value=tmp_path / "ffprobe.exe",
    ):
        with patch("subprocess.run", return_value=mock_zero_proc):
            ok_zero, msg_zero = verify_media_file_integrity(video_file)
            assert ok_zero is False
            assert "재생 시간이 비정상적입니다" in msg_zero


# ==============================================================================
# 1~6단계 생명주기 및 온디맨드 다운로드 부트스트랩 검증
# ==============================================================================


@pytest.mark.ticket("T0110")
def test_step1_custom_user_settings_path_and_download_proceeds(
    clean_env: Path, qtbot
) -> None:
    """[T0110] 1단계: 사용자 지정 설정 경로의 바이너리가 최우선 탐색되고 다운로드가 진행되는지 검증."""
    step1_dir = clean_env / "custom_user_dir"
    step1_dir.mkdir(parents=True, exist_ok=True)
    step1_bin = step1_dir / DEFAULT_FFMPEG_BINARY_NAME
    step1_bin.write_text("fake_step1_ffmpeg", encoding="utf-8")

    update_current_settings(ffmpeg_path=str(step1_bin))

    mock_run = stub_subprocess_ffmpeg_probe(step1_bin)
    with patch("subprocess.run", side_effect=mock_run):
        resolved = resolve_ffmpeg_path()
        assert resolved == step1_bin.resolve()

        card, blocked = create_fake_card(qtbot)
        started = card.trigger_start_download()

        assert started is True
        assert card.status == TaskStatus.DOWNLOADING
        assert len(blocked) == 0


@pytest.mark.ticket("T0110")
def test_step2_meipass_bundle_and_download_proceeds(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, qtbot
) -> None:
    """[T0110] 2단계: 1단계 부재 시 PyInstaller 번들(_MEIPASS) 내 바이너리가 탐색되고 다운로드가 진행되는지 검증."""
    update_current_settings(ffmpeg_path="")

    meipass_dir = clean_env / "bundle_meipass"
    meipass_dir.mkdir(parents=True, exist_ok=True)
    step2_bin = meipass_dir / DEFAULT_FFMPEG_BINARY_NAME
    step2_bin.write_text("fake_step2_ffmpeg", encoding="utf-8")

    monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)

    mock_run = stub_subprocess_ffmpeg_probe(step2_bin)
    with patch("subprocess.run", side_effect=mock_run):
        resolved = resolve_ffmpeg_path()
        assert resolved == step2_bin.resolve()

        card, blocked = create_fake_card(qtbot)
        started = card.trigger_start_download()

        assert started is True
        assert card.status == TaskStatus.DOWNLOADING
        assert len(blocked) == 0


@pytest.mark.ticket("T0110")
def test_step3_system_temp_and_download_proceeds(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, qtbot
) -> None:
    """[T0110] 3단계: 1~2단계 부재 시 %TEMP% 내 런타임 추출 바이너리가 탐색되고 다운로드가 진행되는지 검증."""
    update_current_settings(ffmpeg_path="")

    temp_dir = clean_env / "runtime_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    step3_bin = temp_dir / DEFAULT_FFMPEG_BINARY_NAME
    step3_bin.write_text("fake_step3_ffmpeg", encoding="utf-8")

    monkeypatch.setenv("TEMP", str(temp_dir))
    monkeypatch.setenv("TMP", str(temp_dir))

    mock_run = stub_subprocess_ffmpeg_probe(step3_bin)
    with patch("subprocess.run", side_effect=mock_run):
        resolved = resolve_ffmpeg_path()
        assert resolved == step3_bin.resolve()

        card, blocked = create_fake_card(qtbot)
        started = card.trigger_start_download()

        assert started is True
        assert card.status == TaskStatus.DOWNLOADING
        assert len(blocked) == 0


@pytest.mark.ticket("T0110")
def test_step4_app_bin_dir_and_download_proceeds(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, qtbot
) -> None:
    """[T0110] 4단계: 1~3단계 부재 시 ./bin 디렉터리 내 바이너리가 탐색되고 다운로드가 진행되는지 검증."""
    update_current_settings(ffmpeg_path="")

    cwd_bin_dir = clean_env / "bin"
    cwd_bin_dir.mkdir(parents=True, exist_ok=True)
    step4_bin = cwd_bin_dir / DEFAULT_FFMPEG_BINARY_NAME
    step4_bin.write_text("fake_step4_ffmpeg", encoding="utf-8")

    monkeypatch.chdir(clean_env)

    mock_run = stub_subprocess_ffmpeg_probe(step4_bin)
    with patch("subprocess.run", side_effect=mock_run):
        resolved = resolve_ffmpeg_path()
        assert resolved == step4_bin.resolve()

        card, blocked = create_fake_card(qtbot)
        started = card.trigger_start_download()

        assert started is True
        assert card.status == TaskStatus.DOWNLOADING
        assert len(blocked) == 0


@pytest.mark.ticket("T0110")
def test_step5_system_path_which_and_download_proceeds(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, qtbot
) -> None:
    """[T0110] 5단계: 1~4단계 부재 시 시스템 PATH(which)에서 바이너리를 발견하고 다운로드가 진행되는지 검증."""
    update_current_settings(ffmpeg_path="")

    path_dir = clean_env / "sys_path"
    path_dir.mkdir(parents=True, exist_ok=True)
    step5_bin = path_dir / DEFAULT_FFMPEG_BINARY_NAME
    step5_bin.write_text("fake_step5_ffmpeg", encoding="utf-8")

    monkeypatch.setattr(
        "shutil.which",
        lambda cmd: str(step5_bin) if "ffmpeg" in cmd else None,
    )

    mock_run = stub_subprocess_ffmpeg_probe(step5_bin)
    with patch("subprocess.run", side_effect=mock_run):
        resolved = resolve_ffmpeg_path()
        assert resolved == step5_bin.resolve()

        card, blocked = create_fake_card(qtbot)
        started = card.trigger_start_download()

        assert started is True
        assert card.status == TaskStatus.DOWNLOADING
        assert len(blocked) == 0


@pytest.mark.ticket("T0110")
def test_step6_auto_download_bootstrap_success_and_download_proceeds(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch, qtbot
) -> None:
    """[T0110] 6단계: 1~5단계 실패 시 온디맨드 자동 다운로드 및 압축 해제가 성공하여 다운로드가 진행되는지 검증."""
    update_current_settings(ffmpeg_path="")

    # 1~5단계 바이너리 없음 확인
    assert resolve_ffmpeg_path() is None

    install_dir = clean_env / "auto_downloaded_bin"
    install_dir.mkdir(parents=True, exist_ok=True)
    target_bin = install_dir / DEFAULT_FFMPEG_BINARY_NAME

    # ZIP 아카이브 stub 생성 (ffmpeg 바이너리 포함)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(DEFAULT_FFMPEG_BINARY_NAME, b"downloaded_ffmpeg_binary_payload")
    zip_data = zip_buffer.getvalue()

    # urllib.request.urlopen stub
    mock_response = MagicMock()
    mock_response.read.return_value = zip_data
    mock_response.__enter__.return_value = mock_response

    mock_run = stub_subprocess_ffmpeg_probe(target_bin)

    with patch("urllib.request.urlopen", return_value=mock_response):
        with patch(
            "chzzk_downloader.core.ffmpeg_manager.get_default_ffmpeg_install_dir",
            return_value=install_dir,
        ):
            with patch("subprocess.run", side_effect=mock_run):
                # ensure_ffmpeg_available 6단계 직접 검증
                ok, bin_path = ensure_ffmpeg_available(
                    auto_download=True, target_dir=install_dir
                )
                assert ok is True
                assert bin_path == target_bin.resolve()
                assert target_bin.exists()

                # 작업 카드 다운로드 트리거 시 다운로드 진입 성공 검증
                card, blocked = create_fake_card(qtbot)
                started = card.trigger_start_download()

                assert started is True
                assert card.status == TaskStatus.DOWNLOADING
                assert len(blocked) == 0


@pytest.mark.ticket("T0110")
def test_step6_auto_download_bootstrap_failure_blocks_download(
    clean_env: Path, qtbot
) -> None:
    """[T0110] 6단계: 자동 다운로드 실패 시 다운로드가 차단되고 READY 상태가 유지되는지 검증."""
    update_current_settings(ffmpeg_path="")

    with patch("urllib.request.urlopen", side_effect=Exception("Network error")):
        dl_path = download_ffmpeg_binary(target_dir=clean_env / "fail_bin")
        assert dl_path is None

        card, blocked = create_fake_card(qtbot)
        started = card.trigger_start_download()

        assert started is False
        assert card.status == TaskStatus.READY
        assert len(blocked) == 1
        assert "FFmpeg를 사용할 수 없습니다" in blocked[0]


@pytest.mark.ticket("T0110")
def test_corrupted_intermediate_candidate_falls_back_to_valid_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[T0110] 상위 계층(%TEMP%)에 손상된 바이너리가 있어도 하위 계층(PATH 등)으로 정상 폴백되는지 검증."""
    # 1. %TEMP% 디렉터리에 실행 불가능한 더미 파일 생성
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    corrupted_temp_ffmpeg = temp_dir / DEFAULT_FFMPEG_BINARY_NAME
    corrupted_temp_ffmpeg.write_text("corrupted binary", encoding="utf-8")
    monkeypatch.setenv("TEMP", str(temp_dir))

    # 2. PATH에 정상 작동하는 FFmpeg 가상 경로 설정
    valid_ffmpeg = tmp_path / "bin" / DEFAULT_FFMPEG_BINARY_NAME
    valid_ffmpeg.parent.mkdir()
    valid_ffmpeg.write_text("valid binary", encoding="utf-8")
    monkeypatch.setattr(
        "shutil.which", lambda name: str(valid_ffmpeg) if name == "ffmpeg" else None
    )

    # subprocess.run 실행 시: corrupted 실행 시 returncode 1, valid 실행 시 returncode 0
    def mock_run(cmd, *args, **kwargs):
        cmd_path = str(cmd[0])
        if str(corrupted_temp_ffmpeg) in cmd_path:
            return subprocess.CompletedProcess(
                args=cmd, returncode=1, stdout="", stderr="Corrupted ELF/PE header"
            )
        if str(valid_ffmpeg) in cmd_path:
            if "-version" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout="ffmpeg version 6.1.1-essentials\n",
                    stderr="",
                )
            if "-h" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout="HLS demuxer:\n  -extension_picky\n",
                    stderr="",
                )
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run):
        # verify_executable=True로 검색 시 손상된 %TEMP%를 건너뛰고 PATH의 valid_ffmpeg를 반환해야 함
        resolved = resolve_ffmpeg_path(verify_executable=True)
        assert resolved == valid_ffmpeg.resolve()

        # probe_ffmpeg(None) 역시 정상적으로 valid_ffmpeg로 판정
        probe_res = probe_ffmpeg(None)
        assert probe_res.status == FFmpegStatus.AVAILABLE
        assert probe_res.path == valid_ffmpeg.resolve()


@pytest.mark.ticket("T0110")
def test_ffmpeg_manager_has_no_qt_dependency() -> None:
    """[T0110] [Core 순수성 검증] Core 계층(ffmpeg_manager.py)은 PyQt6 등 GUI 프레임워크에 일체 의존하지 않아야 함."""
    import chzzk_downloader.core.ffmpeg_manager as fm

    source = inspect.getsource(fm)
    assert "PyQt6" not in source, (
        "Core 계층(ffmpeg_manager.py)에 PyQt6 의존성이 존재합니다! 완전 분리되어야 합니다."
    )
    assert "QApplication" not in source, "Core 계층에 QApplication 참조가 존재합니다."
    assert "processEvents" not in source, (
        "Core 계층에 GUI 이벤트 루프 조작(processEvents)이 존재합니다."
    )


@pytest.mark.ticket("T0110")
def test_concurrent_ffmpeg_downloads_no_race_collision(tmp_path: Path) -> None:
    """[T0110] [동시성 검증] 다중 스레드가 동시에 download_ffmpeg_binary를 호출해도 락과 더블체크로 충돌(WinError 32) 없이 안전하게 완료됨을 검증."""
    clear_probe_cache()
    target_bin = tmp_path / DEFAULT_FFMPEG_BINARY_NAME

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr(DEFAULT_FFMPEG_BINARY_NAME, b"concurrent_test_payload")
    zip_data = zip_buffer.getvalue()

    download_count = 0

    def mock_urlopen(req, *args, **kwargs):
        nonlocal download_count
        download_count += 1
        time.sleep(0.05)
        resp = MagicMock()
        resp.read.side_effect = [zip_data, b""]
        resp.headers = {"Content-Length": str(len(zip_data))}
        resp.__enter__.return_value = resp
        return resp

    def mock_run(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="ffmpeg version 6.0-essentials_build Copyright\n",
            stderr="",
        )

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        with patch("subprocess.run", side_effect=mock_run):
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [
                    executor.submit(download_ffmpeg_binary, target_dir=tmp_path)
                    for _ in range(5)
                ]
                results = [f.result() for f in futures]

    # 모든 스레드가 정상적인 바이너리 경로를 반환받음
    for res in results:
        assert res == target_bin
    assert target_bin.exists()
    # 더블체크 락에 의해 실제 원격 다운로드는 1회만 수행됨!
    assert download_count == 1


@pytest.mark.ticket("T0110")
def test_interrupted_download_leaves_no_corrupt_files(tmp_path: Path) -> None:
    """[T0110] [원자성 검증] 압축 해제 및 파일 쓰기 도중 예외 발생 시 목적지 경로에 깨진 바이너리가 남지 않고 완벽히 격리됨을 검증."""
    clear_probe_cache()
    target_bin = tmp_path / DEFAULT_FFMPEG_BINARY_NAME

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr(DEFAULT_FFMPEG_BINARY_NAME, b"valid_zip_content")
    zip_data = zip_buffer.getvalue()

    resp = MagicMock()
    resp.read.return_value = zip_data
    resp.headers = {"Content-Length": str(len(zip_data))}
    resp.__enter__.return_value = resp

    def failing_copy(src, dst):
        dst.write(b"corrupted_partial_data")
        raise OSError("디스크 공간 부족 또는 네트워크 끊김")

    with patch("urllib.request.urlopen", return_value=resp):
        with patch("shutil.copyfileobj", side_effect=failing_copy):
            res = download_ffmpeg_binary(target_dir=tmp_path)
            assert res is None

    # [핵심 검증]: 쓰기 도중 실패 시 목적지 경로에 손상된 파일이 절대 남지 않아야 함!
    assert not target_bin.exists(), (
        "치명적 결함: 쓰기 실패 후에도 목적지 경로에 깨진 바이너리가 잔존합니다!"
    )


@pytest.mark.ticket("T0110")
def test_download_ffmpeg_memory_usage_must_not_spike_with_large_payload(
    tmp_path: Path,
) -> None:
    """[T0110] [메모리 보호 검증] 대용량 바이너리 다운로드 시 전체를 RAM에 적재(resp.read())하지 않고 64KB 스트리밍하여 메모리 피크가 5MB 이하를 유지함을 검증."""
    clear_probe_cache()
    chunk_size = 64 * 1024
    total_chunks = 480  # 약 30MB
    large_chunk = b"A" * chunk_size

    def stream_chunks():
        for _ in range(total_chunks):
            yield large_chunk
        while True:
            yield b""

    gen = stream_chunks()

    resp = MagicMock()
    # read(amt)로 호출되면 64KB씩 스트리밍, read()로 인자 없이 호출되면 30MB 통째로 반환
    resp.read.side_effect = lambda size=None: (
        next(gen) if (size and size > 0) else (large_chunk * total_chunks)
    )
    resp.headers = {"Content-Length": str(chunk_size * total_chunks)}
    resp.__enter__.return_value = resp

    tracemalloc.start()
    tracemalloc.reset_peak()

    with patch("urllib.request.urlopen", return_value=resp):
        download_ffmpeg_binary(target_dir=tmp_path)

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak / (1024 * 1024)
    # [검증]: 64KB 스트리밍 방식은 1MB 미만이어야 함. 만약 기존 전체 적재(resp.read()) 방식이면 30MB 이상 치솟아 실패!
    assert peak_mb < 5.0, (
        f"메모리 폭발 발생! 피크 메모리 점유: {peak_mb:.2f}MB (허용 기준: 5.0MB 미만)"
    )


@pytest.mark.ticket("T0110")
def test_get_default_ffmpeg_install_dir_oserror_fallback_to_temp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """[T0110] 설치 폴더 생성 시 권한 오류(OSError) 발생 시 tempfile 폴백 검증."""

    def raise_oserror(*args, **kwargs):
        raise PermissionError("Access denied")

    monkeypatch.setattr(Path, "mkdir", raise_oserror)
    fallback = get_default_ffmpeg_install_dir()
    assert fallback is not None
    assert "chzzk_downloader" in str(fallback) or str(fallback) in str(tmp_path)


@pytest.mark.ticket("T0110")
def test_download_ffmpeg_binary_mkdir_permission_error() -> None:
    """[T0110] download_ffmpeg_binary에서 디렉터리 생성 실패 시 크래시 없이 None 반환 검증."""
    with patch.object(Path, "mkdir", side_effect=PermissionError("Permission denied")):
        res = download_ffmpeg_binary(target_dir="/nonexistent/forbidden/path")
        assert res is None


@pytest.mark.ticket("T0110")
def test_verify_media_file_integrity_ffprobe_missing_with_valid_magic_bytes(
    tmp_path: Path,
) -> None:
    """[T0110] FFprobe 부재 환경에서 매직 바이트가 유효한 미디어 파일은 통과하고 가짜 텍스트 파일은 차단되는지 검증."""
    # 1. 가짜 텍스트 파일
    fake_txt = tmp_path / "fake.mp4"
    fake_txt.write_text("just text", encoding="utf-8")

    # 2. 유효한 MP4 헤더 파일
    valid_mp4 = tmp_path / "real.mp4"
    valid_mp4.write_bytes(
        b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 64
    )

    with patch(
        "chzzk_downloader.core.ffmpeg_manager.is_ffprobe_available", return_value=False
    ):
        with patch(
            "chzzk_downloader.core.ffmpeg_manager.get_ffprobe_path", return_value=None
        ):
            # 텍스트 파일은 FFprobe 없어도 차단
            ok_txt, msg_txt = verify_media_file_integrity(fake_txt)
            assert ok_txt is False
            assert "컨테이너 헤더 검증 실패" in msg_txt

            # 매직 넘버가 유효한 파일은 FFprobe 부재 시 크기 및 매직 넘버 확인으로 통과
            ok_mp4, msg_mp4 = verify_media_file_integrity(valid_mp4)
            assert ok_mp4 is True
            assert "헤더 매직 넘버" in msg_mp4
