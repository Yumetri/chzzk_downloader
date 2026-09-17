"""T0110. FFmpeg 상태 확인 및 호환성 검증 단위 및 통합 테스트."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6.QtCore import QTimer

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
    """probe_media_file 및 verify_media_file_integrity 매직 넘버 및 재생 시간 무결성 검증 테스트."""
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


def test_corrupted_intermediate_candidate_falls_back_to_valid_candidate(
    tmp_path, monkeypatch
):
    """상위 계층(%TEMP%)에 손상된 바이너리가 있어도 하위 계층(PATH 등)으로 정상 폴백되는지 검증."""
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


def test_ffmpeg_bootstrap_worker_thread(qtbot, tmp_path):
    """FFmpegBootstrapWorker가 백그라운드 스레드에서 블로킹 없이 부트스트랩을 완수하는지 검증."""
    from chzzk_downloader.gui.workers import FFmpegBootstrapWorker

    fake_installed = tmp_path / "bin" / DEFAULT_FFMPEG_BINARY_NAME
    fake_installed.parent.mkdir()
    fake_installed.write_text("fake_ffmpeg", encoding="utf-8")

    worker = FFmpegBootstrapWorker(
        target_dir=str(fake_installed.parent), download_url="http://dummy.url"
    )

    bootstrap_results: list[tuple[bool, str]] = []
    worker.finished_bootstrap.connect(
        lambda ok, path: bootstrap_results.append((ok, path))
    )

    with patch(
        "chzzk_downloader.core.ffmpeg_manager.ensure_ffmpeg_available",
        return_value=(True, fake_installed),
    ):
        with qtbot.waitSignal(worker.finished_bootstrap, timeout=3000):
            worker.start()

    assert len(bootstrap_results) == 1
    assert bootstrap_results[0][0] is True
    assert bootstrap_results[0][1] == str(fake_installed)


def test_ffmpeg_manager_has_no_qt_dependency():
    """[Core 순수성 검증] Core 계층(ffmpeg_manager.py)은 PyQt6 등 GUI 프레임워크에 일체 의존하지 않아야 함."""
    import inspect
    import chzzk_downloader.core.ffmpeg_manager as fm

    source = inspect.getsource(fm)
    assert "PyQt6" not in source, "Core 계층(ffmpeg_manager.py)에 PyQt6 의존성이 존재합니다! 완전 분리되어야 합니다."
    assert "QApplication" not in source, "Core 계층에 QApplication 참조가 존재합니다."
    assert "processEvents" not in source, "Core 계층에 GUI 이벤트 루프 조작(processEvents)이 존재합니다."


def test_ffmpeg_synchronous_download_freezes_ui_event_loop(qtbot, tmp_path):
    """[동기 블로킹 검증] 메인 GUI 스레드에서 순수 동기 다운로드 직접 실행 시 UI 이벤트 루프가 완전히 정지(블로킹)됨을 입증."""
    import io
    import zipfile
    from unittest.mock import MagicMock
    from chzzk_downloader.core.ffmpeg_manager import ensure_ffmpeg_available

    clear_probe_cache()

    # 1. UI 이벤트 루프의 정상 동작을 감시하는 Heartbeat 타이머 등록 (20ms 간격)
    timer_ticks: list[float] = []
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: timer_ticks.append(time.time()))
    timer.start()

    # 2. 원격 네트워크 다운로드 응답 지연 시뮬레이션 (urlopen에서 0.25초 지연)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr(DEFAULT_FFMPEG_BINARY_NAME, b"downloaded_binary_payload")
    zip_data = zip_buffer.getvalue()

    def slow_urlopen(req, *args, **kwargs):
        time.sleep(0.25)
        resp = MagicMock()
        resp.read.return_value = zip_data
        resp.__enter__.return_value = resp
        return resp

    target_bin = tmp_path / DEFAULT_FFMPEG_BINARY_NAME

    def mock_run(cmd, *args, **kwargs):
        cmd_str = [str(c) for c in cmd]
        if str(target_bin) in cmd_str[0] or cmd_str[0] == str(target_bin):
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="ffmpeg version 6.0-essentials_build Copyright\n",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="", stderr="not found"
        )

    start_time = time.time()
    with patch("urllib.request.urlopen", side_effect=slow_urlopen):
        with patch("subprocess.run", side_effect=mock_run):
            # 메인 스레드에서 순수 동기 다운로드 실행
            ensure_ffmpeg_available(auto_download=True, target_dir=tmp_path)

    elapsed = time.time() - start_time

    # [검증]: 순수 동기 다운로드는 메인 스레드를 온전히 블로킹하므로 250ms 동안 타이머 틱이 발생하지 않아야 함!
    # (따라서 UI에서는 이를 직접 부르지 않고 반드시 FFmpegBootstrapWorker를 사용해야 함)
    assert len(timer_ticks) == 0, (
        f"순수 동기 다운로드임에도 UI 이벤트가 처리되었습니다. (틱 수: {len(timer_ticks)})"
    )


def test_ffmpeg_bootstrap_worker_does_not_block_ui_event_loop(qtbot, tmp_path):
    """[해결 검증] 백그라운드 워커 스레드에서 다운로드 실행 시, 네트워크 응답이 지연되어도 UI 이벤트 루프가 멈추지 않고 반응함을 검증."""
    import io
    import zipfile
    from unittest.mock import MagicMock
    from chzzk_downloader.gui.workers import FFmpegBootstrapWorker

    clear_probe_cache()

    # 1. UI 이벤트 루프 감시 Heartbeat 타이머 등록 (20ms 간격)
    timer_ticks: list[float] = []
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: timer_ticks.append(time.time()))
    timer.start()

    # 2. 동일한 원격 네트워크 지연(urlopen 0.25초) 시뮬레이션
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr(DEFAULT_FFMPEG_BINARY_NAME, b"downloaded_binary_payload")
    zip_data = zip_buffer.getvalue()

    def slow_urlopen(req, *args, **kwargs):
        time.sleep(0.25)
        resp = MagicMock()
        resp.read.return_value = zip_data
        resp.__enter__.return_value = resp
        return resp

    target_bin = tmp_path / DEFAULT_FFMPEG_BINARY_NAME

    def mock_run(cmd, *args, **kwargs):
        cmd_str = [str(c) for c in cmd]
        if str(target_bin) in cmd_str[0] or cmd_str[0] == str(target_bin):
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="ffmpeg version 6.0-essentials_build Copyright\n",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="", stderr="not found"
        )

    worker = FFmpegBootstrapWorker(
        target_dir=str(tmp_path), download_url="http://dummy.url"
    )

    with patch("urllib.request.urlopen", side_effect=slow_urlopen):
        with patch("subprocess.run", side_effect=mock_run):
            with qtbot.waitSignal(worker.finished_bootstrap, timeout=3000):
                worker.start()

    # 3. 워커가 백그라운드에서 다운로드하는 동안에도 메인 UI 스레드는 멈추지 않고 타이머 틱(이벤트)을 지속 처리함
    assert len(timer_ticks) >= 5
    assert target_bin.exists()


def test_ui_calls_ffmpeg_download_strictly_in_background_thread(qtbot, tmp_path):
    """[스레드 격리 보장] UI 레벨에서 FFmpeg 다운로드를 수행할 때 메인 GUI 스레드가 아닌 별도 백그라운드 스레드에서만 호출됨을 보장."""
    from PyQt6.QtWidgets import QApplication
    from chzzk_downloader.gui.workers import FFmpegBootstrapWorker

    caller_threads: list[QThread] = []
    fake_bin = tmp_path / DEFAULT_FFMPEG_BINARY_NAME
    fake_bin.write_text("fake_ffmpeg", encoding="utf-8")

    def spy_download(*args, **kwargs):
        caller_threads.append(QThread.currentThread())
        return fake_bin

    worker = FFmpegBootstrapWorker(target_dir=str(tmp_path))
    with patch(
        "chzzk_downloader.core.ffmpeg_manager.download_ffmpeg_binary",
        side_effect=spy_download,
    ):
        with patch("chzzk_downloader.core.ffmpeg_manager.probe_ffmpeg", return_value=(True, "6.0", True)):
            with qtbot.waitSignal(worker.finished_bootstrap, timeout=2000):
                worker.start()

    assert len(caller_threads) == 1
    # [핵심 보장]: 다운로드를 수행한 스레드는 절대 메인 GUI 스레드여서는 안 됨!
    main_thread = QApplication.instance().thread()
    assert caller_threads[0] != main_thread, "치명적 오류: 다운로드가 메인 GUI 스레드에서 동기로 직접 호출되었습니다!"


def test_ui_download_trigger_returns_immediately(qtbot, tmp_path):
    """[논블로킹 보장] UI 레벨에서 다운로드 시작 시 메인 스레드는 0.05초 내로 즉시 반환되어 UI가 멈추지 않아야 함."""
    from chzzk_downloader.gui.workers import FFmpegBootstrapWorker

    worker = FFmpegBootstrapWorker(target_dir=str(tmp_path))

    def slow_ensure(*args, **kwargs):
        time.sleep(0.3)
        return True, tmp_path / DEFAULT_FFMPEG_BINARY_NAME

    with patch("chzzk_downloader.core.ffmpeg_manager.ensure_ffmpeg_available", side_effect=slow_ensure):
        start_time = time.time()
        # 워커 시작 호출 (UI 버튼이나 초기화 시 호출되는 액션)
        worker.start()
        elapsed = time.time() - start_time

        # UI 호출 즉시 리턴 검증 (메인 스레드가 50ms 이상 잡히지 않아야 함)
        assert elapsed < 0.05, f"메인 스레드 블로킹 발생! ({elapsed:.3f}초 소요)"

        with qtbot.waitSignal(worker.finished_bootstrap, timeout=2000):
            pass


def test_get_default_ffmpeg_install_dir_oserror_fallback_to_temp(monkeypatch, tmp_path):
    """설치 폴더 생성 시 권한 오류(OSError) 발생 시 tempfile 폴백 검증."""
    from chzzk_downloader.core.ffmpeg_manager import get_default_ffmpeg_install_dir

    def raise_oserror(*args, **kwargs):
        raise PermissionError("Access denied")

    monkeypatch.setattr(Path, "mkdir", raise_oserror)
    fallback = get_default_ffmpeg_install_dir()
    assert fallback is not None
    assert "chzzk_downloader" in str(fallback) or str(fallback) in str(tmp_path)


def test_download_ffmpeg_binary_mkdir_permission_error():
    """download_ffmpeg_binary에서 디렉터리 생성 실패 시 크래시 없이 None 반환 검증."""
    from chzzk_downloader.core.ffmpeg_manager import download_ffmpeg_binary

    with patch.object(Path, "mkdir", side_effect=PermissionError("Permission denied")):
        res = download_ffmpeg_binary(target_dir="/nonexistent/forbidden/path")
        assert res is None


def test_verify_media_file_integrity_ffprobe_missing_with_valid_magic_bytes(tmp_path):
    """FFprobe 부재 환경에서 매직 바이트가 유효한 미디어 파일은 통과하고 가짜 텍스트 파일은 차단되는지 검증."""
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


def test_task_card_save_dir_mkdir_oserror(qtbot, tmp_path):
    """다운로드 시작 시 저장 경로 생성 실패(권한 부족) 시 다운로드가 차단되고 에러 시그널이 방출되는지 검증."""
    mock_vod = VodInfo(
        video_no="12345", video_title="테스트 영상", channel_name="스트리머"
    )
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/12345",
        status=TaskStatus.READY,
        vod_info=mock_vod,
    )
    qtbot.addWidget(card)

    blocked_reasons: list[str] = []
    card.download_blocked.connect(blocked_reasons.append)

    with patch(
        "chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available", return_value=True
    ):
        with patch.object(
            Path, "mkdir", side_effect=PermissionError("폴더 생성 권한 없음")
        ):
            started = card.trigger_start_download()
            assert started is False
            assert card.status == TaskStatus.READY
            assert len(blocked_reasons) == 1
            assert "저장 폴더를 생성할 수 없습니다" in blocked_reasons[0]
