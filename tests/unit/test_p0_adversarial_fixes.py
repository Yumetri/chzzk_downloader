"""P0 결함 재현 및 검증 테스트 (TDD).

1. _delete_file_safely 빈 경로 시 현재 디렉터리 무차별 삭제 방어
2. VOD 다운로드 시 숨겨진 라이브 스피너 QTimer 정지 (CPU 누수 방어)
3. MainWindow._detach_download_worker 호출 시 VodDownloadWorker 시그널 전수 disconnect
4. SettingsWindow의 모든 모달 창 타이틀이 'Chzzk Downloader'로 통일되었는지 검증
"""

from pathlib import Path
from unittest.mock import patch

from PyQt6.QtWidgets import QMessageBox

from chzzk_downloader.core.task_models import TaskSpec, TaskStatus
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.settings_window import SettingsWindow
from chzzk_downloader.gui.task_card import TaskCardWidget, _delete_file_safely
from chzzk_downloader.gui.workers import VodDownloadWorker


def test_delete_file_safely_empty_or_invalid_path_does_not_collect_cwd(
    tmp_path, monkeypatch
):
    """_delete_file_safely에 빈 경로/공백/루트 경로 전달 시 현재 디렉터리의 파일을 수집하거나 삭제하지 않고 False를 반환하는지 검증."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "important1.txt").write_text("data1", encoding="utf-8")
    (tmp_path / "important2.txt").write_text("data2", encoding="utf-8")

    # 빈 경로 전달
    res_empty = _delete_file_safely(Path(""))
    assert res_empty is False
    assert (tmp_path / "important1.txt").exists()
    assert (tmp_path / "important2.txt").exists()

    # None 또는 공백 전달
    assert _delete_file_safely(None) is False
    assert _delete_file_safely(Path("   ")) is False


def test_vod_downloading_must_not_start_live_spinner(qtbot):
    """VOD 다운로드(is_live=False) 상태에서는 숨겨진 라이브 스피너 타이머가 활성화되지 않아야 함 (CPU 누수 방지)."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/12345",
        status=TaskStatus.READY,
        is_live=False,
    )
    qtbot.addWidget(card)

    card.set_task_status(TaskStatus.DOWNLOADING)

    assert card.live_recording_container.isHidden() is True
    # 숨겨진 라이브 스피너 QTimer가 작동하지 않아야 함
    assert card.spinner._timer.isActive() is False, (
        "VOD 다운로드 중 숨겨진 라이브 녹화 스피너의 QTimer가 활성화되어 CPU를 누수시킴"
    )


def test_detach_download_worker_disconnects_all_signals(qtbot):
    """MainWindow._detach_download_worker 호출 시 VodDownloadWorker의 모든 시그널이 정상적으로 disconnect되는지 검증."""
    main_win = MainWindow()
    qtbot.addWidget(main_win)
    spec = TaskSpec(
        task_id="test_detach_p0",
        video_url="https://chzzk.naver.com/video/1",
        save_path=Path("test.mp4"),
    )
    worker = VodDownloadWorker(spec, parent=main_win)

    # MainWindow._start_vod_download에서 연결하는 것과 동일한 시그널 바인딩
    worker.progress_updated.connect(lambda p: None)
    worker.download_finished.connect(lambda t, p: None)
    worker.download_failed.connect(lambda *args: None)
    worker.download_stopped.connect(lambda t: None)
    worker.finished.connect(lambda: None)

    # 워커 분리 실행 (closeEvent 시나리오)
    main_win._detach_download_worker(worker, disconnect_signals=True)

    # 시그널 수신자(receiver)가 전수 disconnect되어 0이어야 함
    assert worker.receivers(worker.progress_updated) == 0
    assert worker.receivers(worker.download_finished) == 0
    assert worker.receivers(worker.download_failed) == 0
    assert worker.receivers(worker.download_stopped) == 0


def test_settings_window_modals_use_unified_title(qtbot, monkeypatch):
    """SettingsWindow의 모든 모달 호출 시 'Chzzk Downloader' 타이틀이 사용되는지 검증."""
    win = SettingsWindow()
    qtbot.addWidget(win)

    captured_titles: list[str] = []

    def mock_warning(parent, title, text, *args, **kwargs):
        captured_titles.append(title)

    def mock_info(parent, title, text, *args, **kwargs):
        captured_titles.append(title)

    monkeypatch.setattr(QMessageBox, "warning", mock_warning)
    monkeypatch.setattr(QMessageBox, "information", mock_info)

    # 1. 폴더 오류 (업데이트 실패 시뮬레이션)
    monkeypatch.setattr(
        "chzzk_downloader.gui.settings_window.update_current_settings",
        lambda **kw: (False, "쓰기 권한 오류"),
    )
    monkeypatch.setattr(
        "PyQt6.QtWidgets.QFileDialog.getExistingDirectory",
        lambda *a, **k: "C:/Restricted",
    )
    win._on_choose_folder()

    # 2. 쿠키 파일 로드 실패 시뮬레이션
    monkeypatch.setattr(
        "PyQt6.QtWidgets.QFileDialog.getOpenFileName",
        lambda *a, **k: ("dummy_cookies.txt", "txt"),
    )
    monkeypatch.setattr(
        "chzzk_downloader.gui.settings_window.load_cookie_file",
        lambda path: (False, "유효하지 않은 쿠키 파일"),
    )
    win._on_import_file()

    # 3. 쿠키 파일 내보내기 실패 시뮬레이션
    monkeypatch.setattr(
        "PyQt6.QtWidgets.QFileDialog.getSaveFileName",
        lambda *a, **k: ("dummy_export.txt", "txt"),
    )
    monkeypatch.setattr(
        "chzzk_downloader.gui.settings_window.export_cookie_file",
        lambda path: (False, "내보내기 권한 오류"),
    )
    win._on_export_clicked()

    # 4. 쿠키 초기화 실패 시뮬레이션
    with patch(
        "chzzk_downloader.gui.settings_window.ask_confirm_dialog", return_value=True
    ):
        monkeypatch.setattr(
            "chzzk_downloader.gui.settings_window.clear_cookies",
            lambda: (False, "삭제 실패"),
        )
        win._on_clear_clicked()

    assert len(captured_titles) >= 4
    for title in captured_titles:
        assert title == "Chzzk Downloader", f"모달 창 제목 규격 위반: {title}"
