"""설정 파일(settings.json) 저장, 로드, 손상 복구 및 원자적 쓰기 단위 테스트."""

from pathlib import Path
from unittest.mock import patch

import pytest

from chzzk_downloader.core.settings_manager import (
    AppSettings,
    get_current_settings,
    load_settings,
    save_settings,
    update_current_settings,
    validate_download_dir,
)


@pytest.mark.ticket("T0108")
def test_default_settings_initialization_and_dir_creation(tmp_path: Path) -> None:
    """[T0108] 설정 파일 부재 시 load_settings 호출 시 기본값 생성 및 다운로드 폴더 자동 생성 검증."""
    settings_file = tmp_path / "new_settings.json"
    assert not settings_file.exists()

    settings = load_settings(settings_file)
    assert settings_file.exists()
    assert settings.default_quality == "최고 화질"
    assert settings.file_extension == ".mp4"
    assert settings.download_dir.exists()
    assert settings.download_dir.is_dir()


@pytest.mark.ticket("T0108")
def test_settings_save_and_reload(tmp_path: Path) -> None:
    """[T0108] 설정 변경 및 저장 후 다시 로드했을 때 데이터 영속성 검증."""
    settings_file = tmp_path / "save_reload.json"
    custom_dir = tmp_path / "custom_download"
    custom_dir.mkdir()

    new_settings = AppSettings(
        download_dir=custom_dir,
        default_quality="1080p",
        file_extension=".ts",
    )
    ok = save_settings(new_settings, settings_file)
    assert ok is True

    reloaded = load_settings(settings_file)
    assert reloaded.download_dir.resolve() == custom_dir.resolve()
    assert reloaded.default_quality == "1080p"
    assert reloaded.file_extension == ".ts"


@pytest.mark.ticket("T0108")
def test_settings_corrupted_json_fallback(tmp_path: Path) -> None:
    """[T0108] 설정 파일이 손상된 경우 크래시 없이 기본값으로 안전하게 자동 복구되는지 검증."""
    settings_file = tmp_path / "broken_settings.json"
    settings_file.write_text("INVALID_JSON{broken...", encoding="utf-8")

    settings = load_settings(settings_file)
    assert settings.default_quality == "최고 화질"
    assert settings.file_extension == ".mp4"
    assert settings.download_dir.exists()


@pytest.mark.ticket("T0108")
def test_validate_download_dir(tmp_path: Path) -> None:
    """[T0108] 디렉터리 존재 여부 및 실질적 쓰기 권한 테스트 검증."""
    valid_dir = tmp_path / "valid_dir"
    valid_dir.mkdir()

    ok, msg = validate_download_dir(valid_dir)
    assert ok is True
    assert msg == ""

    # 1. 존재하지 않는 경로
    non_existent = tmp_path / "not_found"
    ok, msg = validate_download_dir(non_existent)
    assert ok is False
    assert "존재하지 않습니다" in msg

    # 2. 파일 경로
    a_file = tmp_path / "a_file.txt"
    a_file.write_text("dummy", encoding="utf-8")
    ok, msg = validate_download_dir(a_file)
    assert ok is False
    assert "폴더가 아닙니다" in msg

    # 3. 쓰기 실패 모킹
    with patch.object(Path, "write_text", side_effect=PermissionError("쓰기 거부")):
        ok, msg = validate_download_dir(valid_dir)
        assert ok is False
        assert "쓰기 권한이 없습니다" in msg


@pytest.mark.ticket("T0108")
def test_settings_recovery_from_zero_byte_and_truncated_file(tmp_path: Path) -> None:
    """[T0108] 0바이트 빈 파일이나 부분 쓰기 도중 중단된(truncated) JSON 발생 시 안전한 기본값 복구 검증."""
    # 1. 0바이트 빈 파일
    settings_file = tmp_path / "zero_byte.json"
    settings_file.write_text("", encoding="utf-8")
    settings = load_settings(settings_file)
    assert settings.default_quality == "최고 화질"
    assert settings.file_extension == ".mp4"
    assert settings_file.stat().st_size > 0

    # 2. 부분 쓰기 중단 (Truncated JSON)
    truncated_file = tmp_path / "truncated.json"
    truncated_file.write_text('{"download_dir": "C:/incomplete', encoding="utf-8")
    settings2 = load_settings(truncated_file)
    assert settings2.default_quality == "최고 화질"
    assert settings2.file_extension == ".mp4"


@pytest.mark.ticket("T0108")
def test_settings_atomic_save_leaves_no_tmp_on_failure(tmp_path: Path) -> None:
    """[T0108] 설정 저장 중 예외 발생 시 기존 설정 파일이 보존되고 임시 파일이 디스크에 잔류하지 않는지 검증."""
    settings_file = tmp_path / "atomic_test.json"
    initial_settings = AppSettings(
        download_dir=tmp_path, default_quality="1080p", file_extension=".mp4"
    )
    save_settings(initial_settings, settings_file)
    orig_content = settings_file.read_text(encoding="utf-8")

    # Path.replace 도중 크래시/I/O 실패 모킹
    with patch.object(Path, "replace", side_effect=OSError("Disk write failure")):
        new_settings = AppSettings(
            download_dir=tmp_path, default_quality="360p", file_extension=".ts"
        )
        ok = save_settings(new_settings, settings_file)
        assert ok is False

    # 원본 파일이 손상되지 않고 보존됨
    assert settings_file.read_text(encoding="utf-8") == orig_content
    # 잔여 .tmp 파일이 정리되었는지 확인
    tmp_files = list(settings_file.parent.glob("*.tmp"))
    assert len(tmp_files) == 0


@pytest.mark.ticket("T0108")
def test_validate_download_dir_network_timeout_and_cleanup(tmp_path: Path) -> None:
    """[T0108] 네트워크 지연이나 디스크 쓰기 I/O 실패 시 안전하게 False를 반환하고 임시 파일을 남기지 않는지 검증."""
    target_dir = tmp_path / "network_test"
    target_dir.mkdir()

    with patch.object(Path, "write_text", side_effect=TimeoutError("Network timeout")):
        ok, msg = validate_download_dir(target_dir)
        assert ok is False
        assert "폴더 쓰기 권한이 없습니다" in msg

    # 임시 파일이 깨끗이 정리되었는지 확인
    tmp_files = list(target_dir.glob(".write_test_*.tmp"))
    assert len(tmp_files) == 0


@pytest.mark.ticket("T0110")
def test_settings_save_and_reload_ffmpeg_path(tmp_path: Path) -> None:
    """[T0110] settings.json에 FFmpeg 경로 저장 및 앱 재실행 복원 검증."""
    custom_ffmpeg = tmp_path / "custom" / "ffmpeg.exe"
    custom_ffmpeg.parent.mkdir(parents=True)
    custom_ffmpeg.write_text("binary", encoding="utf-8")

    ok, msg = update_current_settings(ffmpeg_path=str(custom_ffmpeg))
    assert ok is True
    assert get_current_settings().ffmpeg_path == str(custom_ffmpeg)

    reloaded = get_current_settings()
    assert reloaded.ffmpeg_path == str(custom_ffmpeg)

    # 초기화 (빈 문자열)
    ok2, _ = update_current_settings(ffmpeg_path="")
    assert ok2 is True
    assert get_current_settings().ffmpeg_path == ""
