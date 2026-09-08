"""FFmpeg 1단계~6단계 생명주기 탐색, 온디맨드 설치 및 다운로드 진행 엔드투엔드 검증 테스트."""

from __future__ import annotations

import io
import os
import subprocess
import sys
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
    is_ffmpeg_available,
    resolve_ffmpeg_path,
)
from chzzk_downloader.core.settings_manager import (
    set_custom_settings_path,
    update_current_settings,
)
from chzzk_downloader.core.ytdlp import VodInfo
from chzzk_downloader.gui.task_card import TaskCardWidget, TaskStatus


@pytest.fixture(autouse=True)
def reset_probe_state():
    """모든 테스트 전후로 프로빙 캐시를 무효화합니다."""
    clear_probe_cache()
    yield
    clear_probe_cache()


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    """외부 환경(PATH, TEMP, _MEIPASS)을 격리하는 fixture."""
    # 1. settings 격리
    settings_file = tmp_path / "test_settings.json"
    set_custom_settings_path(settings_file)
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

    yield tmp_path

    set_custom_settings_path(None)


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
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="not found")

    return mock_run


# ==============================================================================
# 1단계: 사용자 지정 경로 (Settings.ffmpeg_path) 검증
# ==============================================================================
def test_step1_custom_user_settings_path_and_download_proceeds(clean_env, qtbot):
    """1단계: 사용자 지정 설정 경로의 바이너리가 최우선 탐색되고 다운로드가 진행되는지 검증."""
    step1_dir = clean_env / "custom_user_dir"
    step1_dir.mkdir(parents=True, exist_ok=True)
    step1_bin = step1_dir / DEFAULT_FFMPEG_BINARY_NAME
    step1_bin.write_text("fake_step1_ffmpeg", encoding="utf-8")

    # 설정에 사용자 지정 경로 등록
    update_current_settings(ffmpeg_path=str(step1_bin))

    mock_run = stub_subprocess_ffmpeg_probe(step1_bin)
    with patch("subprocess.run", side_effect=mock_run):
        # 1단계 해석 확인
        resolved = resolve_ffmpeg_path()
        assert resolved == step1_bin.resolve()

        # 작업 카드 다운로드 트리거
        card, blocked = create_fake_card(qtbot)
        started = card.trigger_start_download()

        assert started is True
        assert card.status == TaskStatus.DOWNLOADING
        assert len(blocked) == 0


# ==============================================================================
# 2단계: PyInstaller 번들 디렉터리 (sys._MEIPASS) 검증
# ==============================================================================
def test_step2_meipass_bundle_and_download_proceeds(clean_env, monkeypatch, qtbot):
    """2단계: 1단계 부재 시 sys._MEIPASS 번들 바이너리가 탐색되고 다운로드가 진행되는지 검증."""
    # 1단계는 비워둠
    update_current_settings(ffmpeg_path="")

    meipass_dir = clean_env / "meipass_bundle"
    meipass_dir.mkdir(parents=True, exist_ok=True)
    step2_bin = meipass_dir / DEFAULT_FFMPEG_BINARY_NAME
    step2_bin.write_text("fake_step2_ffmpeg", encoding="utf-8")

    monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)

    mock_run = stub_subprocess_ffmpeg_probe(step2_bin)
    with patch("subprocess.run", side_effect=mock_run):
        # 2단계 해석 확인
        resolved = resolve_ffmpeg_path()
        assert resolved == step2_bin.resolve()

        card, blocked = create_fake_card(qtbot)
        started = card.trigger_start_download()

        assert started is True
        assert card.status == TaskStatus.DOWNLOADING
        assert len(blocked) == 0


# ==============================================================================
# 3단계: 시스템 임시 디렉터리 (%TEMP%/ffmpeg.exe, Hitomi 호환) 검증
# ==============================================================================
def test_step3_system_temp_and_download_proceeds(clean_env, monkeypatch, qtbot):
    """3단계: 1~2단계 부재 시 %TEMP% 내 런타임 추출 바이너리가 탐색되고 다운로드가 진행되는지 검증."""
    update_current_settings(ffmpeg_path="")

    temp_dir = clean_env / "runtime_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    step3_bin = temp_dir / DEFAULT_FFMPEG_BINARY_NAME
    step3_bin.write_text("fake_step3_ffmpeg", encoding="utf-8")

    monkeypatch.setenv("TEMP", str(temp_dir))
    monkeypatch.setenv("TMP", str(temp_dir))

    mock_run = stub_subprocess_ffmpeg_probe(step3_bin)
    with patch("subprocess.run", side_effect=mock_run):
        # 3단계 해석 확인
        resolved = resolve_ffmpeg_path()
        assert resolved == step3_bin.resolve()

        card, blocked = create_fake_card(qtbot)
        started = card.trigger_start_download()

        assert started is True
        assert card.status == TaskStatus.DOWNLOADING
        assert len(blocked) == 0


# ==============================================================================
# 4단계: 애플리케이션 실행 디렉터리 (./bin/ffmpeg.exe) 검증
# ==============================================================================
def test_step4_app_bin_dir_and_download_proceeds(clean_env, monkeypatch, qtbot):
    """4단계: 1~3단계 부재 시 ./bin 디렉터리 내 바이너리가 탐색되고 다운로드가 진행되는지 검증."""
    update_current_settings(ffmpeg_path="")

    cwd_bin_dir = clean_env / "bin"
    cwd_bin_dir.mkdir(parents=True, exist_ok=True)
    step4_bin = cwd_bin_dir / DEFAULT_FFMPEG_BINARY_NAME
    step4_bin.write_text("fake_step4_ffmpeg", encoding="utf-8")

    monkeypatch.chdir(clean_env)

    mock_run = stub_subprocess_ffmpeg_probe(step4_bin)
    with patch("subprocess.run", side_effect=mock_run):
        # 4단계 해석 확인
        resolved = resolve_ffmpeg_path()
        assert resolved == step4_bin.resolve()

        card, blocked = create_fake_card(qtbot)
        started = card.trigger_start_download()

        assert started is True
        assert card.status == TaskStatus.DOWNLOADING
        assert len(blocked) == 0


# ==============================================================================
# 5단계: 시스템 환경변수 PATH (shutil.which) 검증
# ==============================================================================
def test_step5_system_path_which_and_download_proceeds(clean_env, monkeypatch, qtbot):
    """5단계: 1~4단계 부재 시 시스템 PATH 상의 ffmpeg가 탐색되고 다운로드가 진행되는지 검증."""
    update_current_settings(ffmpeg_path="")

    system_path_dir = clean_env / "usr_bin"
    system_path_dir.mkdir(parents=True, exist_ok=True)
    step5_bin = system_path_dir / DEFAULT_FFMPEG_BINARY_NAME
    step5_bin.write_text("fake_step5_ffmpeg", encoding="utf-8")

    monkeypatch.setattr("shutil.which", lambda cmd: str(step5_bin) if "ffmpeg" in cmd else None)

    mock_run = stub_subprocess_ffmpeg_probe(step5_bin)
    with patch("subprocess.run", side_effect=mock_run):
        # 5단계 해석 확인
        resolved = resolve_ffmpeg_path()
        assert resolved == step5_bin.resolve()

        card, blocked = create_fake_card(qtbot)
        started = card.trigger_start_download()

        assert started is True
        assert card.status == TaskStatus.DOWNLOADING
        assert len(blocked) == 0


# ==============================================================================
# 6단계: 온디맨드 자동 다운로드 (부트스트랩) 성공 시 다운로드 진행 검증
# ==============================================================================
def test_step6_auto_download_bootstrap_success_and_download_proceeds(clean_env, qtbot):
    """6단계: 1~5단계 모두 없을 때 원격 자동 다운로드(ZIP)가 수행되고 다운로드가 진행되는지 검증."""
    update_current_settings(ffmpeg_path="")

    # 1~5단계 바이너리 없음 확인
    assert resolve_ffmpeg_path() is None

    install_dir = clean_env / "auto_downloaded_bin"
    install_dir.mkdir(parents=True, exist_ok=True)
    target_bin = install_dir / DEFAULT_FFMPEG_BINARY_NAME

    # ZIP 아카이브 stub 생성 (ffmpeg.exe 포함)
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
        with patch("chzzk_downloader.core.ffmpeg_manager.get_default_ffmpeg_install_dir", return_value=install_dir):
            with patch("subprocess.run", side_effect=mock_run):
                # ensure_ffmpeg_available 6단계 직접 검증
                ok, bin_path = ensure_ffmpeg_available(auto_download=True, target_dir=install_dir)
                assert ok is True
                assert bin_path == target_bin.resolve()
                assert target_bin.exists()

                # 작업 카드 다운로드 트리거 시 다운로드 진입 성공 검증
                card, blocked = create_fake_card(qtbot)
                started = card.trigger_start_download()

                assert started is True
                assert card.status == TaskStatus.DOWNLOADING
                assert len(blocked) == 0


# ==============================================================================
# 6단계: 온디맨드 자동 다운로드 실패 시 다운로드 차단(T07/M10 연동) 검증
# ==============================================================================
def test_step6_auto_download_bootstrap_failure_blocks_download(clean_env, qtbot):
    """6단계: 1~5단계 부재 및 원격 다운로드 네트워크 실패 시 다운로드가 차단되는지 검증."""
    update_current_settings(ffmpeg_path="")

    # 1~5단계 없음
    assert resolve_ffmpeg_path() is None

    install_dir = clean_env / "fail_download_bin"

    # urllib 네트워크 오류 stub (예: 연결 실패)
    with patch("urllib.request.urlopen", side_effect=OSError("Network connection refused")):
        with patch("chzzk_downloader.core.ffmpeg_manager.get_default_ffmpeg_install_dir", return_value=install_dir):
            # 6단계 다운로드 실패 확인
            downloaded = download_ffmpeg_binary(target_dir=install_dir)
            assert downloaded is None

            ok, bin_path = ensure_ffmpeg_available(auto_download=True, target_dir=install_dir)
            assert ok is False
            assert bin_path is None

            # 작업 카드 다운로드 트리거 시 실패 및 차단 검증
            card, blocked = create_fake_card(qtbot)
            started = card.trigger_start_download()

            assert started is False
            assert card.status == TaskStatus.READY  # 상태 전이 거부
            assert len(blocked) == 1
            assert "FFmpeg를 사용할 수 없습니다" in blocked[0]

