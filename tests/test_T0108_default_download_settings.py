"""T0108. 기본 다운로드 설정 단위 및 통합 테스트."""

from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6.QtWidgets import QMessageBox

from chzzk_downloader.config import AVAILABLE_EXTENSIONS, AVAILABLE_QUALITIES
from chzzk_downloader.core.settings_manager import (
    AppSettings,
    get_current_settings,
    get_default_download_dir,
    load_settings,
    save_settings,
    set_custom_settings_path,
    validate_download_dir,
)
from chzzk_downloader.gui.settings_window import SettingsWindow


@pytest.fixture
def test_settings_env(tmp_path):
    """임시 디렉터리의 settings.json 경로를 사용하도록 격리하는 fixture."""
    test_settings_file = tmp_path / "test_settings.json"
    set_custom_settings_path(test_settings_file)
    yield test_settings_file
    set_custom_settings_path(None)


def test_default_settings_initialization_and_dir_creation(test_settings_env):
    """설정 파일이 없을 때 load_settings 호출 시 기본값 생성, 파일 저장 및 다운로드 디렉터리 자동 생성 검증."""
    assert not test_settings_env.exists()

    settings = load_settings(test_settings_env)
    assert test_settings_env.exists()
    assert settings.default_quality == "최고 화질"
    assert settings.file_extension == ".mp4"
    assert settings.download_dir.exists()
    assert settings.download_dir.is_dir()


def test_settings_save_and_reload(test_settings_env, tmp_path):
    """설정 변경 및 저장 후 다시 로드했을 때 데이터 영속성 검증."""
    custom_dir = tmp_path / "custom_download"
    custom_dir.mkdir()

    new_settings = AppSettings(
        download_dir=custom_dir,
        default_quality="1080p",
        file_extension=".ts",
    )
    ok = save_settings(new_settings, test_settings_env)
    assert ok is True

    reloaded = load_settings(test_settings_env)
    assert reloaded.download_dir.resolve() == custom_dir.resolve()
    assert reloaded.default_quality == "1080p"
    assert reloaded.file_extension == ".ts"


def test_settings_corrupted_json_fallback(test_settings_env):
    """설정 파일이 손상된 경우 크래시 없이 기본값으로 안전하게 자동 복구되는지 검증."""
    test_settings_env.write_text("INVALID_JSON{broken...", encoding="utf-8")

    settings = load_settings(test_settings_env)
    assert settings.default_quality == "최고 화질"
    assert settings.file_extension == ".mp4"
    assert settings.download_dir.exists()


def test_validate_download_dir(tmp_path):
    """디렉터리 존재 여부 및 실질적 쓰기 권한 테스트 검증."""
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


def test_settings_window_general_group_layout_and_readonly(qtbot, test_settings_env):
    """SettingsWindow에서 '일반' 그룹이 '쿠키 관리' 그룹 위에 배치되고 읽기 전용 및 드롭다운 항목이 정상인지 검증."""
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()

    # 1. 배치 순서 검증: 일반 그룹이 쿠키 관리 그룹보다 위에 위치
    layout = window.layout()
    assert layout is not None
    general_idx = layout.indexOf(window.general_group)
    cookie_idx = layout.indexOf(window.cookie_group)
    assert general_idx != -1
    assert cookie_idx != -1
    assert general_idx < cookie_idx

    # 2. 저장 폴더 입력창은 읽기 전용이어야 함 (직접 입력 불가)
    assert window.folder_input.isReadOnly() is True

    # 3. 화질 드롭다운 검증
    qualities_in_combo = [
        window.quality_combo.itemText(i) for i in range(window.quality_combo.count())
    ]
    assert qualities_in_combo == list(AVAILABLE_QUALITIES)
    assert window.quality_combo.currentText() == "최고 화질"

    # 4. 파일 확장자 드롭다운 검증
    exts_in_combo = [
        window.ext_combo.itemText(i) for i in range(window.ext_combo.count())
    ]
    assert exts_in_combo == list(AVAILABLE_EXTENSIONS)
    assert window.ext_combo.currentText() == ".mp4"


def test_settings_window_choose_folder_success(qtbot, test_settings_env, tmp_path):
    """폴더 아이콘 클릭 후 시스템 디렉터리 선택 시 UI 갱신 및 설정 영속화 검증."""
    target_dir = tmp_path / "new_target_folder"
    target_dir.mkdir()

    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()

    with patch(
        "PyQt6.QtWidgets.QFileDialog.getExistingDirectory",
        return_value=str(target_dir),
    ):
        window.folder_btn.click()

    # UI 및 저장된 설정 확인
    assert window.folder_input.text() == str(target_dir.resolve())
    current = get_current_settings()
    assert current.download_dir.resolve() == target_dir.resolve()


def test_settings_window_choose_folder_invalid_warning(
    qtbot, test_settings_env, tmp_path
):
    """쓰기 불가 또는 잘못된 폴더 선택 시 경고 팝업이 노출되고 이전 유효 경로가 유지되는지 검증."""
    orig_dir = get_default_download_dir().resolve()

    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()

    assert Path(window.folder_input.text()).resolve() == orig_dir

    # 쓰기 권한 없는 경로 모킹
    with patch(
        "PyQt6.QtWidgets.QFileDialog.getExistingDirectory",
        return_value=str(tmp_path / "unwritable"),
    ):
        with patch.object(QMessageBox, "warning") as mock_warn:
            window.folder_btn.click()
            mock_warn.assert_called_once()
            assert "폴더 오류" in mock_warn.call_args[0][1]

    # 이전 유효 경로 유지 확인
    assert Path(window.folder_input.text()).resolve() == orig_dir
    assert get_current_settings().download_dir.resolve() == orig_dir


def test_settings_window_quality_and_ext_change_auto_saves(qtbot, test_settings_env):
    """화질 및 확장자 드롭다운 변경 시 즉시 settings.json에 영속화(Auto-save)되는지 검증."""
    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()

    # 1. 화질 변경
    window.quality_combo.setCurrentText("720p")
    assert get_current_settings().default_quality == "720p"

    # 파일에서 직접 읽어서 영속화 확인
    reloaded = load_settings(test_settings_env)
    assert reloaded.default_quality == "720p"

    # 2. 파일 확장자 변경
    window.ext_combo.setCurrentText(".ts")
    assert get_current_settings().file_extension == ".ts"

    reloaded2 = load_settings(test_settings_env)
    assert reloaded2.file_extension == ".ts"


def test_settings_recovery_from_zero_byte_and_truncated_file(test_settings_env):
    """0바이트 빈 파일이나 부분 쓰기 도중 중단된(truncated) JSON 발생 시 안전한 기본값 복구 검증."""
    # 1. 0바이트 빈 파일
    test_settings_env.write_text("", encoding="utf-8")
    settings = load_settings(test_settings_env)
    assert settings.default_quality == "최고 화질"
    assert settings.file_extension == ".mp4"
    assert test_settings_env.stat().st_size > 0

    # 2. 부분 쓰기 중단 (Truncated JSON)
    test_settings_env.write_text('{"download_dir": "C:/incomplete', encoding="utf-8")
    settings2 = load_settings(test_settings_env)
    assert settings2.default_quality == "최고 화질"
    assert settings2.file_extension == ".mp4"


def test_settings_atomic_save_leaves_no_tmp_on_failure(test_settings_env, tmp_path):
    """설정 저장 중 예외 발생 시 기존 설정 파일이 보존되고 임시 파일이 디스크에 잔류하지 않는지 검증."""
    initial_settings = AppSettings(
        download_dir=tmp_path, default_quality="1080p", file_extension=".mp4"
    )
    save_settings(initial_settings, test_settings_env)
    orig_content = test_settings_env.read_text(encoding="utf-8")

    # Path.replace 도중 크래시/I/O 실패 모킹
    with patch.object(Path, "replace", side_effect=OSError("Disk write failure")):
        new_settings = AppSettings(
            download_dir=tmp_path, default_quality="360p", file_extension=".ts"
        )
        ok = save_settings(new_settings, test_settings_env)
        assert ok is False

    # 원본 파일이 손상되지 않고 보존됨
    assert test_settings_env.read_text(encoding="utf-8") == orig_content
    # 잔여 .tmp 파일이 정리되었는지 확인
    tmp_files = list(test_settings_env.parent.glob("*.tmp"))
    assert len(tmp_files) == 0


def test_settings_window_folder_dialog_cancelled_or_error_maintains_path(
    qtbot, test_settings_env
):
    """탐색기 창에서 사용자가 취소(ESC/취소 버튼)하거나 탐색기 에러 발생 시 UI와 설정이 변경 없이 안전하게 유지되는지 검증."""
    orig_dir = get_default_download_dir().resolve()

    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()

    assert Path(window.folder_input.text()).resolve() == orig_dir

    # 1. 탐색기 취소 (빈 문자열 반환)
    with patch("PyQt6.QtWidgets.QFileDialog.getExistingDirectory", return_value=""):
        window.folder_btn.click()
        assert Path(window.folder_input.text()).resolve() == orig_dir
        assert get_current_settings().download_dir.resolve() == orig_dir

    # 2. 탐색기 호출 자체에서 시스템 예외 발생 시 크래시 방어
    with patch(
        "PyQt6.QtWidgets.QFileDialog.getExistingDirectory",
        side_effect=RuntimeError("Explorer system error"),
    ):
        with patch.object(QMessageBox, "warning") as mock_warn:
            window.folder_btn.click()
            mock_warn.assert_called_once()
            assert "폴더 오류" in mock_warn.call_args[0][1]

        # 경로가 유지되는지 확인
        assert Path(window.folder_input.text()).resolve() == orig_dir


def test_validate_download_dir_network_timeout_and_cleanup(tmp_path):
    """네트워크 지연이나 디스크 쓰기 I/O 실패 시 안전하게 False를 반환하고 임시 파일을 남기지 않는지 검증."""
    target_dir = tmp_path / "network_test"
    target_dir.mkdir()

    with patch.object(Path, "write_text", side_effect=TimeoutError("Network timeout")):
        ok, msg = validate_download_dir(target_dir)
        assert ok is False
        assert "폴더 쓰기 권한이 없습니다" in msg

    # 임시 파일이 깨끗이 정리되었는지 확인
    tmp_files = list(target_dir.glob(".write_test_*.tmp"))
    assert len(tmp_files) == 0


def test_settings_window_immediate_close_after_selection(
    qtbot, test_settings_env, tmp_path
):
    """경로 설정 후 지연 없이 창이 즉시 닫혀도 원자적 저장 완료로 인해 데이터가 유실되지 않는지 검증."""
    new_dir = tmp_path / "quick_close_dir"
    new_dir.mkdir()

    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()

    with patch(
        "PyQt6.QtWidgets.QFileDialog.getExistingDirectory",
        return_value=str(new_dir),
    ):
        window.folder_btn.click()

    # 즉시 창 닫기
    window.close()

    # 새 설정이 파일에 안전하게 반영되어 있는지 확인
    reloaded = load_settings(test_settings_env)
    assert reloaded.download_dir.resolve() == new_dir.resolve()
