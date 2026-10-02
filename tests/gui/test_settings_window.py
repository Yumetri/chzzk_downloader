"""환경설정 창(SettingsWindow) UI 구성, 폴더 선택, 자동 저장, 모덜리스 동작 및 Zero-Config 검증 GUI 테스트."""

from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from chzzk_downloader.config import (
    AVAILABLE_EXTENSIONS,
    AVAILABLE_QUALITIES,
)
from chzzk_downloader.core.cookie_manager import (
    SessionStatus,
    clear_cookies,
    get_last_session_status,
    has_valid_cookies,
    save_cookies_text,
)
from chzzk_downloader.core.settings_manager import (
    get_current_settings,
    get_default_download_dir,
    get_settings_file_path,
    load_settings,
)
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.settings_window import SettingsWindow


@pytest.fixture
def main_window(qtbot):
    """메인 창 인스턴스를 생성하고 표시하는 fixture."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    return window


@pytest.mark.ticket("T0108")
def test_settings_window_general_group_layout_and_readonly(qtbot) -> None:
    """[T0108] SettingsWindow에서 '일반' 그룹이 '쿠키 관리' 그룹 위에 배치되고 읽기 전용 및 드롭다운 항목이 정상인지 검증."""
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


@pytest.mark.ticket("T0108")
def test_settings_window_choose_folder_success(qtbot, tmp_path: Path) -> None:
    """[T0108] 폴더 아이콘 클릭 후 시스템 디렉터리 선택 시 UI 갱신 및 설정 영속화 검증."""
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


@pytest.mark.ticket("T0108")
def test_settings_window_choose_folder_invalid_warning(qtbot, tmp_path: Path) -> None:
    """[T0108] 쓰기 불가 또는 잘못된 폴더 선택 시 경고 팝업이 노출되고 이전 유효 경로가 유지되는지 검증."""
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


@pytest.mark.ticket("T0108")
def test_settings_window_quality_and_ext_change_auto_saves(qtbot) -> None:
    """[T0108] 화질 및 확장자 드롭다운 변경 시 즉시 settings.json에 영속화(Auto-save)되는지 검증."""
    settings_file = get_settings_file_path()
    assert settings_file is not None

    window = SettingsWindow()
    qtbot.addWidget(window)
    window.show()

    # 1. 화질 변경
    window.quality_combo.setCurrentText("720p")
    assert get_current_settings().default_quality == "720p"

    # 파일에서 직접 읽어서 영속화 확인
    reloaded = load_settings(settings_file)
    assert reloaded.default_quality == "720p"

    # 2. 파일 확장자 변경
    window.ext_combo.setCurrentText(".ts")
    assert get_current_settings().file_extension == ".ts"

    reloaded2 = load_settings(settings_file)
    assert reloaded2.file_extension == ".ts"


@pytest.mark.ticket("T0108")
def test_settings_window_folder_dialog_cancelled_or_error_maintains_path(qtbot) -> None:
    """[T0108] 탐색기 창에서 사용자가 취소(ESC/취소 버튼)하거나 탐색기 에러 발생 시 UI와 설정이 변경 없이 안전하게 유지되는지 검증."""
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


@pytest.mark.ticket("T0108")
def test_settings_window_immediate_close_after_selection(qtbot, tmp_path: Path) -> None:
    """[T0108] 경로 설정 후 지연 없이 창이 즉시 닫혀도 원자적 저장 완료로 인해 데이터가 유실되지 않는지 검증."""
    settings_file = get_settings_file_path()
    assert settings_file is not None

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
    reloaded = load_settings(settings_file)
    assert reloaded.download_dir.resolve() == new_dir.resolve()


@pytest.mark.ticket("T0109")
def test_settings_window_vod_auto_download_toggle(qtbot) -> None:
    """[T0109] SettingsWindow에서 VOD 자동 다운로드 스위치 조작 시 settings.json에 영속화되는지 검증."""
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


@pytest.mark.ticket("T0110")
def test_settings_window_clean_without_ffmpeg_widget(qtbot) -> None:
    """[T0110] SettingsWindow가 불필요한 FFmpeg 수동 설정 위젯 없이 깔끔하게 일반/쿠키만 구성되는지 검증."""
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


@pytest.mark.ticket("T0106")
def test_settings_window_modeless_and_actions(qtbot, tmp_path: Path) -> None:
    """[T0106] SettingsWindow의 Modeless 동작, 상태 표시, 보기/내보내기/초기화 액션 검증."""
    window = SettingsWindow()
    qtbot.addWidget(window)
    assert window.isModal() is False

    # 초기 상태
    assert "등록된 쿠키 없음" in window.status_label.text()

    # 쿠키 저장 후 상태 갱신 확인
    save_cookies_text("NID_AUT=set_aut; NID_SES=set_ses")
    window.refresh_status()
    assert "NID_AUT, NID_SES 확인" in window.status_label.text()

    # 파일 불러오기 테스트
    cookie_txt = tmp_path / "imported.txt"
    cookie_txt.write_text(
        ".naver.com\tTRUE\t/\tTRUE\t2147483647\tNID_AUT\timported_aut\n",
        encoding="utf-8",
    )
    with patch(
        "PyQt6.QtWidgets.QFileDialog.getOpenFileName",
        return_value=(str(cookie_txt), "txt"),
    ):
        with patch.object(QMessageBox, "information"):
            with qtbot.waitSignal(window.cookies_updated, timeout=1000):
                window._on_import_file()
    assert has_valid_cookies() is True
    assert "NID_AUT 확인" in window.status_label.text()

    # 초기화 클릭 (QMessageBox Yes 모킹)
    with patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
    ):
        with patch.object(QMessageBox, "information"):
            with qtbot.waitSignal(window.cookies_updated, timeout=1000):
                window._on_clear_clicked()

    assert has_valid_cookies() is False
    assert "등록된 쿠키 없음" in window.status_label.text()


@pytest.mark.ticket("T0106")
def test_main_window_settings_button_opens_modeless_window(main_window, qtbot) -> None:
    """[T0106] 메인 창 상단 설정 버튼 클릭 시 Modeless 설정 창이 정상적으로 열리는지 검증."""
    qtbot.mouseClick(main_window.settings_btn, Qt.MouseButton.LeftButton)

    assert hasattr(main_window, "_settings_window")
    assert main_window._settings_window is not None
    assert main_window._settings_window.isVisible() is True
    assert main_window._settings_window.isModal() is False

    # 다시 클릭 시에도 새 창이 중복 생성되지 않고 기존 창 유지
    existing = main_window._settings_window
    qtbot.mouseClick(main_window.settings_btn, Qt.MouseButton.LeftButton)
    assert main_window._settings_window is existing


@pytest.mark.ticket("PR08")
def test_clear_cookies_failure_handling(qtbot) -> None:
    """[PR08] 쿠키 파일 삭제(unlink) 실패 시 clear_cookies()가 False를 반환하고 경고 팝업이 뜨는지 검증."""
    save_cookies_text("NID_AUT=original_aut; NID_SES=original_ses")

    with patch.object(Path, "unlink", side_effect=PermissionError("Permission Denied")):
        ok, msg = clear_cookies()
        assert ok is False
        assert "쿠키 파일 삭제 실패" in msg

        status, _ = get_last_session_status()
        assert status != SessionStatus.NO_COOKIES

    settings_win = SettingsWindow()
    qtbot.addWidget(settings_win)

    with patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
    ):
        with patch.object(
            Path, "unlink", side_effect=PermissionError("Permission Denied")
        ):
            with patch.object(QMessageBox, "warning") as mock_warning:
                settings_win._on_clear_clicked()
                mock_warning.assert_called_once()
                assert "초기화 실패" in mock_warning.call_args[0][1]
