"""다운로드 완료/실패 처리 및 토스트/UI 완료 피드백 단위 테스트 (T0111 3단계)."""

from unittest.mock import patch

import pytest
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication

from chzzk_downloader.core.task_models import TaskStatus
from chzzk_downloader.core.ytdlp import VodFormatInfo, VodInfo
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.task_card import TaskCardWidget
from chzzk_downloader.gui.toast import ToastType


@pytest.fixture
def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    return instance


@pytest.fixture
def sample_vod_info():
    return VodInfo(
        video_no="33333",
        video_title="완료 및 실패 테스트 방송",
        channel_name="치지직스트리머",
        duration=7200,  # 2시간
        formats=[VodFormatInfo("1080p", "1080p", 60)],
    )


def test_task_completed_sets_final_file_path_and_shows_toast(
    app, sample_vod_info, tmp_path
):
    """다운로드 완료 시 카드의 final_file_path 저장 및 완료 성공 토스트(T08) 노출 검증."""
    window = MainWindow()
    card = TaskCardWidget(
        "https://chzzk.naver.com/video/33333",
        status=TaskStatus.DOWNLOADING,
        vod_info=sample_vod_info,
        parent=window,
    )
    window.task_list_widget.add_task_card(card)

    fake_file = tmp_path / "[치지직스트리머] 완료 및 실패 테스트 방송 (33333).mp4"
    fake_file.write_bytes(b"dummy")

    with patch.object(window.toast, "show_toast") as mock_show_toast:
        # TaskManager로부터 완료 수신 모사
        window._on_task_completed("33333", str(fake_file))

    # 1. 카드의 상태 및 파일 경로 보존 검증
    assert card.status == TaskStatus.COMPLETED
    assert card.final_file_path == fake_file
    assert "완료" in card.status_label.text()
    assert "02:00:00" in card.status_label.text()

    # 2. 완료 토스트 노출 검증
    mock_show_toast.assert_called_once()
    args, kwargs = mock_show_toast.call_args
    toast_msg = args[0]
    toast_type = args[1]
    assert "완료" in toast_msg
    assert fake_file.name in toast_msg
    assert toast_type == ToastType.SUCCESS

    window.close()


def test_completed_card_hover_toolbar_buttons_exist(app, sample_vod_info, tmp_path):
    """완료 상태 카드의 2번 위치 호버 툴바에 폴더 열기(📁), 재생(▶), 삭제(✕) 버튼이 존재하는지 검증."""
    card = TaskCardWidget(
        "https://chzzk.naver.com/video/33333",
        status=TaskStatus.READY,
        vod_info=sample_vod_info,
    )
    fake_file = tmp_path / "test.mp4"
    fake_file.write_bytes(b"dummy")
    card.set_completed(fake_file)

    assert hasattr(card, "open_folder_btn"), (
        "완료 상태용 open_folder_btn(📁)이 없습니다."
    )
    assert hasattr(card, "play_btn"), "완료 상태용 play_btn(▶)이 없습니다."
    assert hasattr(card, "delete_btn"), "delete_btn(✕)이 없습니다."

    # COMPLETED 상태에서 호버 시 open_folder_btn, play_btn, delete_btn이 보여야 함
    card._show_hover_toolbar(True)
    assert not card.open_folder_btn.isHidden()
    assert not card.play_btn.isHidden()
    assert not card.delete_btn.isHidden()

    card._show_hover_toolbar(False)
    assert card.open_folder_btn.isHidden()
    assert card.play_btn.isHidden()
    assert card.delete_btn.isHidden()


def test_open_folder_action_with_existing_file(app, sample_vod_info, tmp_path):
    """📁 폴더 열기 버튼 클릭 시 탐색기 실행 검증."""
    card = TaskCardWidget(
        "https://chzzk.naver.com/video/33333",
        status=TaskStatus.COMPLETED,
        vod_info=sample_vod_info,
    )
    fake_file = tmp_path / "test.mp4"
    fake_file.write_bytes(b"dummy")
    card.set_completed(fake_file)

    with (
        patch("subprocess.Popen") as mock_popen,
        patch("PyQt6.QtGui.QDesktopServices.openUrl") as mock_open_url,
    ):
        card.open_folder()
        # Windows 탐색기 select 호출 또는 QDesktopServices 호출 확인
        assert mock_popen.called or mock_open_url.called


def test_open_folder_action_file_missing_warning(app, sample_vod_info, tmp_path):
    """파일이 디스크에 없을 때 open_folder가 크래시 없이 경고 시그널 또는 부모 토스트를 트리거하는지 검증."""
    window = MainWindow()
    card = TaskCardWidget(
        "https://chzzk.naver.com/video/33333",
        status=TaskStatus.COMPLETED,
        vod_info=sample_vod_info,
        parent=window,
    )
    window.task_list_widget.add_task_card(card)

    non_existent = tmp_path / "not_found.mp4"
    card.set_completed(non_existent)

    with patch.object(window.toast, "show_toast") as mock_show_toast:
        card.open_folder()
        mock_show_toast.assert_called_once()
        args, _ = mock_show_toast.call_args
        assert "찾을 수 없습니다" in args[0]

    window.close()


def test_play_media_action_with_existing_file(app, sample_vod_info, tmp_path):
    """▶ 영상 재생 버튼 클릭 시 기본 미디어 플레이어로 오픈 검증."""
    card = TaskCardWidget(
        "https://chzzk.naver.com/video/33333",
        status=TaskStatus.COMPLETED,
        vod_info=sample_vod_info,
    )
    fake_file = tmp_path / "test.mp4"
    fake_file.write_bytes(b"dummy")
    card.set_completed(fake_file)

    with patch("PyQt6.QtGui.QDesktopServices.openUrl") as mock_open_url:
        card.play_media()
        mock_open_url.assert_called_once_with(QUrl.fromLocalFile(str(fake_file)))


def test_play_media_action_file_missing_warning(app, sample_vod_info, tmp_path):
    """파일이 디스크에 없을 때 play_media가 크래시 없이 경고 토스트를 트리거하는지 검증."""
    window = MainWindow()
    card = TaskCardWidget(
        "https://chzzk.naver.com/video/33333",
        status=TaskStatus.COMPLETED,
        vod_info=sample_vod_info,
        parent=window,
    )
    window.task_list_widget.add_task_card(card)

    non_existent = tmp_path / "not_found.mp4"
    card.set_completed(non_existent)

    with patch.object(window.toast, "show_toast") as mock_show_toast:
        card.play_media()
        mock_show_toast.assert_called_once()
        args, _ = mock_show_toast.call_args
        assert "찾을 수 없습니다" in args[0]

    window.close()


def test_task_failed_preserves_error_details_for_task_info_window(app, sample_vod_info):
    """다운로드 실패 시 error_type, error_message, traceback_str이 보존되고 TaskInfoWindow에 전달되는지 검증."""
    window = MainWindow()
    card = TaskCardWidget(
        "https://chzzk.naver.com/video/33333",
        status=TaskStatus.DOWNLOADING,
        vod_info=sample_vod_info,
        parent=window,
    )
    window.task_list_widget.add_task_card(card)

    tb = "Traceback (most recent call last):\n  File 'test.py', line 1, in <module>\nRuntimeError: Connection reset"
    window._on_task_failed("33333", "RuntimeError", "Connection reset", tb)

    assert card.status == TaskStatus.FAILED_DOWNLOAD
    assert card.error_type == "RuntimeError"
    assert card.error_message == "Connection reset"
    assert card.traceback_str == tb

    # TaskInfoWindow 열기 테스트
    card.open_task_info_window()
    assert card._info_win is not None
    assert card._info_win.isVisible()
    # TaskInfoWindow 텍스트에 Traceback 및 에러 메시지가 포함되어 있는지 검증
    text_content = card._info_win.text_edit.toPlainText()
    assert "RuntimeError" in text_content
    assert "Connection reset" in text_content
    assert "Traceback" in text_content

    card._info_win.close()
    window.close()


def test_task_failed_toast_branches(app, sample_vod_info):
    """실패 사유별(성인/로그인 만료, 잘못된 URL, 일반 다운로드 실패) 토스트 분기 검증."""
    window = MainWindow()
    c1 = TaskCardWidget(
        "https://chzzk.naver.com/video/login_err",
        status=TaskStatus.READY,
        task_id="login_err",
        parent=window,
    )
    c2 = TaskCardWidget(
        "https://chzzk.naver.com/video/invalid_err",
        status=TaskStatus.READY,
        task_id="invalid_err",
        parent=window,
    )
    c3 = TaskCardWidget(
        "https://chzzk.naver.com/video/down_err",
        status=TaskStatus.READY,
        task_id="down_err",
        parent=window,
    )
    for c in (c1, c2, c3):
        window.task_list_widget.add_task_card(c)

    # 1. 로그인/성인인증 필요 실패 ➔ T06 액션 토스트 노출
    with patch.object(window.toast, "show_action_toast") as mock_action_toast:
        window._on_task_failed(
            "login_err", "LoginRequiredError", "성인 인증이 필요한 영상입니다.", ""
        )
        mock_action_toast.assert_called_once()
        assert c1.status == TaskStatus.FAILED_LOGIN_REQUIRED

    # 2. 비공개/존재하지 않는 URL 실패 ➔ T04/T05 에러 토스트 노출
    with patch.object(window.toast, "show_toast") as mock_show_toast:
        window._on_task_failed(
            "invalid_err", "VodNotFoundError", "비공개 동영상입니다.", ""
        )
        mock_show_toast.assert_called_once()
        args, _ = mock_show_toast.call_args
        assert args[1] == ToastType.ERROR
        assert c2.status == TaskStatus.FAILED_INVALID

    # 3. 일반 다운로드 오류 ➔ 에러 토스트 노출
    with patch.object(window.toast, "show_toast") as mock_show_toast:
        window._on_task_failed("down_err", "DownloadError", "HTTP Error 503", "")
        mock_show_toast.assert_called_once()
        args, _ = mock_show_toast.call_args
        assert "다운로드 실패" in args[0]
        assert "503" in args[0]
        assert args[1] == ToastType.ERROR
        assert c3.status == TaskStatus.FAILED_DOWNLOAD

    window.close()


def test_reset_for_redownload_clears_previous_session_file_and_error(app, tmp_path):
    """[결함 1 검증] reset_for_redownload 시 이전 세션의 final_file_path, error_type, traceback_str 초기화."""

    card = TaskCardWidget("https://chzzk.naver.com/video/11111")
    fake_file = tmp_path / "old_video.mp4"
    fake_file.write_bytes(b"dummy")
    card.set_completed(fake_file)
    card.set_failed(
        TaskStatus.FAILED_DOWNLOAD, "Old error", "OldErrType", "Old Traceback"
    )

    assert card.final_file_path == fake_file
    assert card.error_type == "OldErrType"
    assert card.traceback_str == "Old Traceback"

    # 동일 VOD 재입력으로 재다운로드 리셋 트리거
    card.reset_for_redownload()

    assert card.status == TaskStatus.ANALYZING
    assert card.final_file_path is None, (
        f"final_file_path leaked: {card.final_file_path}"
    )
    assert card.error_type == "", f"error_type leaked: {card.error_type}"
    assert card.traceback_str == "", f"traceback_str leaked: {card.traceback_str}"


def test_task_info_window_reopen_and_close_event_cleanup(app):
    """[결함 2 검증] TaskInfoWindow 재오픈 시 인스턴스 누수 방지 및 MainWindow 종료 시 창 정리."""
    from PyQt6 import sip

    window = MainWindow()
    card = TaskCardWidget("https://chzzk.naver.com/video/11111", parent=window)
    window.task_list_widget.add_task_card(card)

    card.open_task_info_window()
    first_win = card._info_win
    assert first_win is not None
    assert first_win.isVisible()

    first_win.close()  # 사용자가 닫기 클릭
    app.processEvents()
    card.open_task_info_window()  # 사용자가 다시 열기 클릭
    second_win = card._info_win

    assert second_win is not None
    # 첫 번째 창은 파기되었거나 재사용되어야 함
    assert sip.isdeleted(first_win) or (second_win is first_win)

    # MainWindow closeEvent 시 열려 있는 TaskInfoWindow도 함께 닫혀야 함
    window.close()
    app.processEvents()
    assert sip.isdeleted(second_win) or not second_win.isVisible()


def test_open_folder_and_play_empty_path_defense(app):
    """[결함 3 검증] 빈 경로("") 또는 디렉토리 경로에 대해 탐색기/플레이어가 현재 폴더('.')로 실행되지 않고 방어 토스트 표시."""
    window = MainWindow()
    card = TaskCardWidget(
        "https://chzzk.naver.com/video/11111", status=TaskStatus.READY, parent=window
    )
    window.task_list_widget.add_task_card(card)
    card.set_completed("")  # 빈 경로 설정

    with (
        patch.object(window.toast, "show_toast") as mock_toast,
        patch("subprocess.Popen") as mock_popen,
        patch("PyQt6.QtGui.QDesktopServices.openUrl") as mock_open_url,
    ):
        card.open_folder()
        assert not mock_popen.called, (
            f"탐색기가 현재 작업 디렉토리('.')로 잘못 실행되었습니다: {mock_popen.call_args}"
        )
        assert not mock_open_url.called
        mock_toast.assert_called_once()
        assert "찾을 수 없습니다" in mock_toast.call_args[0][0]

    with (
        patch.object(window.toast, "show_toast") as mock_toast,
        patch("PyQt6.QtGui.QDesktopServices.openUrl") as mock_open_url,
    ):
        card.play_media()
        assert not mock_open_url.called
        mock_toast.assert_called_once()
        assert "찾을 수 없습니다" in mock_toast.call_args[0][0]

    window.close()


def test_cleanup_worker_deletes_qthread_object(app):
    """[결함 4 검증] VodDownloadWorker 종료 및 _cleanup_worker 호출 시 QThread C++ 객체가 deleteLater로 해제됨."""
    from pathlib import Path

    from PyQt6 import sip

    from chzzk_downloader.core.task_models import TaskSpec
    from chzzk_downloader.gui.workers import VodDownloadWorker

    window = MainWindow()
    spec = TaskSpec(
        "task_1",
        "http://fake",
        False,
        "title",
        "streamer",
        "1080p",
        "mp4",
        Path("f.mp4"),
    )
    worker = VodDownloadWorker(spec, parent=window)
    window._download_workers["task_1"] = worker

    # 워커 정리 호출
    window._cleanup_worker("task_1", worker)
    app.processEvents()

    assert sip.isdeleted(worker) or worker not in window.children()
    window.close()


def test_http_401_403_error_mapping_inconsistency(app):
    """[결함 5 검증] 다운로드 실패 시 HTTP 401/403/Forbidden 에러에 대해 FAILED_LOGIN_REQUIRED 및 액션 토스트 연동."""
    window = MainWindow()
    card = TaskCardWidget(
        "https://chzzk.naver.com/video/401401",
        status=TaskStatus.READY,
        task_id="401401",
        parent=window,
    )
    window.task_list_widget.add_task_card(card)

    with patch.object(window.toast, "show_action_toast") as mock_action_toast:
        # 실제 yt-dlp의 401 Unauthorized 에러 시뮬레이션
        window._on_task_failed(
            "401401", "HTTPError", "HTTP Error 401: Unauthorized", ""
        )
        assert card.status == TaskStatus.FAILED_LOGIN_REQUIRED, (
            f"HTTP 401 에러는 FAILED_LOGIN_REQUIRED여야 하나 {card.status}로 오분류되었습니다."
        )
        mock_action_toast.assert_called_once()
    window.close()


def test_phantom_toast_on_nonexistent_or_deleted_task(app):
    """[결함 6 검증] 목록에 없거나 이미 삭제된 작업에 대해 완료/실패 팬텀 토스트가 노출되지 않음."""
    window = MainWindow()

    with patch.object(window.toast, "show_toast") as mock_toast:
        # 삭제된 작업 ID에 대한 완료/실패 시그널 도달
        window._on_task_completed("deleted_task", "video.mp4")
        assert not mock_toast.called, (
            "삭제된 작업에 대해 완료 팬텀 토스트가 노출되었습니다."
        )

        window._on_task_failed("deleted_task", "RuntimeError", "error msg", "")
        assert not mock_toast.called, (
            "삭제된 작업에 대해 실패 팬텀 토스트가 노출되었습니다."
        )

    window.close()


def test_hover_toolbar_auto_sync_on_status_change(app):
    """[결함 7 검증] 마우스가 카드 위에 있는 상태(underMouse)에서 COMPLETED 전이 시 호버 툴바가 즉시 동기화됨."""
    from unittest.mock import patch

    card = TaskCardWidget(
        "https://chzzk.naver.com/video/11111", status=TaskStatus.DOWNLOADING
    )
    card.show()
    with patch.object(card, "underMouse", return_value=True):
        card.set_completed("dummy.mp4")
        assert not card.open_folder_btn.isHidden()
        assert not card.play_btn.isHidden()
        assert not card.delete_btn.isHidden()
    card.close()


def test_format_task_info_completed_done_flag_and_final_path(app, tmp_path):
    """[결함 8 검증] TaskInfoWindow의 format_task_info에서 COMPLETED 작업의 done이 True이고 final_file_path가 정상 노출됨."""
    from chzzk_downloader.gui.task_info_window import format_task_info

    card = TaskCardWidget(
        "https://chzzk.naver.com/video/11111", status=TaskStatus.READY
    )
    fake_file = tmp_path / "completed_video.mp4"
    fake_file.write_bytes(b"dummy")
    card.set_completed(fake_file)

    info_str = format_task_info(card)
    assert (
        "done: True" in info_str
        or "valid / done: True / True" in info_str
        or "COMPLETED" in info_str
    )
    assert "completed_video.mp4" in info_str
