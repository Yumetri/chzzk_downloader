"""TaskManager와 UI(MainWindow, TaskCardWidget) 결합 단위 테스트 (T0111 1단계)."""

from unittest.mock import patch

import pytest
from PyQt6.QtWidgets import QApplication

from chzzk_downloader.core.task_manager import TaskManager
from chzzk_downloader.core.task_models import TaskSpec, TaskStatus
from chzzk_downloader.core.ytdlp import VodFormatInfo, VodInfo
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.task_card import TaskCardWidget


@pytest.fixture
def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    return instance


@pytest.fixture
def mock_vod_info_factory():
    def _create(video_no: str, title: str = "테스트 영상"):
        return VodInfo(
            video_no=video_no,
            video_title=title,
            channel_name="스트리머",
            duration=3600,
            thumbnail_url="",
            formats=[
                VodFormatInfo(format_id="1080p", height=1080, fps=60),
                VodFormatInfo(format_id="720p", height=720, fps=30),
            ],
        )

    return _create


def test_main_window_owns_task_manager(app):
    """MainWindow가 TaskManager 인스턴스를 소유하고 시그널을 연동하는지 검증."""
    window = MainWindow()
    assert hasattr(window, "task_manager")
    assert isinstance(window.task_manager, TaskManager)
    assert window.task_manager.max_concurrent_vod == 3
    window.close()


def test_task_card_has_task_id_and_creates_spec(app, mock_vod_info_factory):
    """TaskCardWidget이 고유 task_id를 보유하고 TaskSpec을 올바르게 생성하는지 검증."""
    vod_info = mock_vod_info_factory("12345", "첫번째 영상")
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/12345",
        status=TaskStatus.READY,
        vod_info=vod_info,
        video_no="12345",
    )
    assert hasattr(card, "task_id")
    assert card.task_id == "12345"

    spec = card.get_task_spec()
    assert isinstance(spec, TaskSpec)
    assert spec.task_id == "12345"
    assert spec.title == "첫번째 영상"
    assert spec.streamer == "스트리머"
    assert spec.is_live is False
    card.deleteLater()


def test_vod_slots_scheduling_integration(app, mock_vod_info_factory, tmp_path):
    """3슬롯 만석 시 4번째 작업이 QUEUED로 진입하고, 슬롯 회수 시 자동 승계되는지 UI 결합 검증."""
    with patch(
        "chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available", return_value=True
    ):
        window = MainWindow()
        window.task_manager.max_concurrent_vod = 3

        cards: list[TaskCardWidget] = []
        for i in range(1, 5):
            v_no = f"video_{i}"
            info = mock_vod_info_factory(v_no, f"영상 {i}")
            card = TaskCardWidget(
                raw_url=f"https://chzzk.naver.com/video/{v_no}",
                status=TaskStatus.READY,
                vod_info=info,
                video_no=v_no,
                parent=window,
            )
            card.custom_download_dir = tmp_path
            window.task_list_widget.add_task_card(card)
            cards.append(card)

        # 1, 2, 3번째 작업 시작 -> 슬롯 여유 있으므로 즉시 DOWNLOADING
        for i in range(3):
            ok = cards[i].trigger_start_download()
            assert ok is True
            assert cards[i].status == TaskStatus.DOWNLOADING
            assert cards[i].task_id in window.task_manager.get_running_vod_tasks()

        # 4번째 작업 시작 -> 슬롯 만석이므로 QUEUED 상태로 진입해야 함
        ok4 = cards[3].trigger_start_download()
        assert ok4 is True
        assert cards[3].status == TaskStatus.QUEUED
        assert "대기 중" in cards[3].status_label.text()
        assert "대기 순번: 1번" in cards[3].status_label.text()

        # 첫 번째 작업이 완료(report_completed)되면 슬롯이 회수되어 4번째 작업이 자동으로 DOWNLOADING으로 전이
        window.task_manager.report_completed("video_1", str(tmp_path / "video_1.mp4"))
        assert cards[0].status == TaskStatus.COMPLETED
        assert cards[3].status == TaskStatus.DOWNLOADING
        assert cards[3].task_id in window.task_manager.get_running_vod_tasks()

        window.close()


def test_queued_task_order_update_on_queue_updated(
    app, mock_vod_info_factory, tmp_path
):
    """대기열에 복수의 작업이 있을 때 대기 순번이 실시간으로 동기화되는지 검증."""
    with patch(
        "chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available", return_value=True
    ):
        window = MainWindow()
        window.task_manager.max_concurrent_vod = 1  # 1슬롯으로 테스트

        # 1번 (실행), 2번 (대기 1순번), 3번 (대기 2순번)
        c1 = TaskCardWidget(
            "https://chzzk.naver.com/video/v1",
            status=TaskStatus.READY,
            vod_info=mock_vod_info_factory("v1"),
            parent=window,
        )
        c2 = TaskCardWidget(
            "https://chzzk.naver.com/video/v2",
            status=TaskStatus.READY,
            vod_info=mock_vod_info_factory("v2"),
            parent=window,
        )
        c3 = TaskCardWidget(
            "https://chzzk.naver.com/video/v3",
            status=TaskStatus.READY,
            vod_info=mock_vod_info_factory("v3"),
            parent=window,
        )
        for c in (c1, c2, c3):
            c.custom_download_dir = tmp_path
            window.task_list_widget.add_task_card(c)

        c1.trigger_start_download()
        c2.trigger_start_download()
        c3.trigger_start_download()

        assert c1.status == TaskStatus.DOWNLOADING
        assert c2.status == TaskStatus.QUEUED
        assert "대기 순번: 1번" in c2.status_label.text()
        assert c3.status == TaskStatus.QUEUED
        assert "대기 순번: 2번" in c3.status_label.text()

        # c1 완료 시 c2가 실행되고 c3의 대기 순번은 1번으로 당겨져야 함
        window.task_manager.report_completed("v1", str(tmp_path / "v1.mp4"))
        assert c2.status == TaskStatus.DOWNLOADING
        assert c3.status == TaskStatus.QUEUED
        assert "대기 순번: 1번" in c3.status_label.text()

        window.close()


def test_task_card_deletion_removes_from_task_manager_and_advances_queue(
    app, mock_vod_info_factory, tmp_path
):
    """실행 중인 카드를 UI에서 삭제할 때 TaskManager에서 슬롯이 회수되고 대기 카드가 자동 승계되는지 검증."""
    with patch(
        "chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available", return_value=True
    ):
        window = MainWindow()
        window.task_manager.max_concurrent_vod = 1

        c1 = TaskCardWidget(
            "https://chzzk.naver.com/video/v1",
            status=TaskStatus.READY,
            vod_info=mock_vod_info_factory("v1"),
            parent=window,
        )
        c2 = TaskCardWidget(
            "https://chzzk.naver.com/video/v2",
            status=TaskStatus.READY,
            vod_info=mock_vod_info_factory("v2"),
            parent=window,
        )
        for c in (c1, c2):
            c.custom_download_dir = tmp_path
            window.task_list_widget.add_task_card(c)

        c1.trigger_start_download()
        c2.trigger_start_download()

        assert c1.status == TaskStatus.DOWNLOADING
        assert c2.status == TaskStatus.QUEUED

        # 실행 중인 c1의 delete_requested를 트리거하여 삭제
        c1.delete_requested.emit()

        # TaskManager에서 v1이 제거되고, v2가 DOWNLOADING으로 자동 승계되어야 함
        assert "v1" not in window.task_manager.get_running_vod_tasks()
        assert c2.status == TaskStatus.DOWNLOADING
        assert "v2" in window.task_manager.get_running_vod_tasks()

        window.close()


def test_deleted_card_event_safety(app, mock_vod_info_factory, tmp_path):
    """이미 삭제된 카드에 대해 백그라운드 이벤트가 방출되어도 크래시 없이 안전하게 무시되는지 검증."""
    with patch(
        "chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available", return_value=True
    ):
        window = MainWindow()
        c1 = TaskCardWidget(
            "https://chzzk.naver.com/video/v_del",
            status=TaskStatus.READY,
            vod_info=mock_vod_info_factory("v_del"),
            parent=window,
        )
        c1.custom_download_dir = tmp_path
        window.task_list_widget.add_task_card(c1)
        c1.trigger_start_download()

        # 카드를 UI에서 수동 삭제 처리
        c1.is_deleted = True

        # TaskManager 시그널 직접 방출 시 예외 크래시 없음
        window._on_task_status_changed(
            "v_del", TaskStatus.DOWNLOADING, TaskStatus.COMPLETED
        )
        window._on_task_completed("v_del", str(tmp_path / "v_del.mp4"))
        window._on_task_failed("v_del", "Error", "네트워크 에러", "")
        window._on_queue_updated(0, 0, 0)

        window.close()


def test_stop_download_desync_and_slot_advance(app, mock_vod_info_factory, tmp_path):
    """[결함 1] 중지(■) 클릭 시 TaskManager cancel_task 연동 및 후속 대기 작업 자동 승계 검증."""
    with patch(
        "chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available", return_value=True
    ):
        window = MainWindow()
        window.task_manager.max_concurrent_vod = 1

        c1 = TaskCardWidget(
            "https://chzzk.naver.com/video/v1",
            status=TaskStatus.READY,
            vod_info=mock_vod_info_factory("v1"),
            parent=window,
        )
        c2 = TaskCardWidget(
            "https://chzzk.naver.com/video/v2",
            status=TaskStatus.READY,
            vod_info=mock_vod_info_factory("v2"),
            parent=window,
        )
        for c in (c1, c2):
            c.custom_download_dir = tmp_path
            window.task_list_widget.add_task_card(c)

        c1.trigger_start_download()
        c2.trigger_start_download()

        assert c1.status == TaskStatus.DOWNLOADING
        assert c2.status == TaskStatus.QUEUED

        with patch(
            "chzzk_downloader.gui.task_card.ask_confirm_dialog", return_value=True
        ):
            c1.trigger_stop_download()

        # TaskManager에서도 v1이 STOPPED로 전이되고 슬롯이 반환되어 c2가 DOWNLOADING으로 자동 승계되어야 함
        assert window.task_manager.get_task_status("v1") == TaskStatus.STOPPED
        assert c2.status == TaskStatus.DOWNLOADING
        assert "v2" in window.task_manager.get_running_vod_tasks()

        window.close()


def test_queued_task_duplicate_url_rejected_with_warning(
    app, mock_vod_info_factory, tmp_path
):
    """[결함 2] QUEUED 상태의 VOD URL 재입력 시 ANALYZING으로 리셋되지 않고 거부 토스트가 표시되는지 검증."""
    with patch(
        "chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available", return_value=True
    ):
        window = MainWindow()
        window.task_manager.max_concurrent_vod = 1

        c1 = TaskCardWidget(
            "https://chzzk.naver.com/video/10001",
            status=TaskStatus.READY,
            vod_info=mock_vod_info_factory("10001"),
            parent=window,
        )
        c2 = TaskCardWidget(
            "https://chzzk.naver.com/video/10002",
            status=TaskStatus.READY,
            vod_info=mock_vod_info_factory("10002"),
            parent=window,
        )
        for c in (c1, c2):
            c.custom_download_dir = tmp_path
            window.task_list_widget.add_task_card(c)

        c1.trigger_start_download()
        c2.trigger_start_download()

        assert c1.status == TaskStatus.DOWNLOADING
        assert c2.status == TaskStatus.QUEUED

        # 대기 중인 c2의 URL을 재입력하고 다운로드 버튼 클릭
        window.url_input.setText("https://chzzk.naver.com/video/10002")
        with patch.object(
            window, "_confirm_redownload_dialog", return_value=True
        ) as mock_dialog:
            window._on_download_clicked()
            # QUEUED 상태이므로 재다운로드 모달이 뜨지 않고 경고 토스트가 떠야 함
            assert mock_dialog.call_count == 0

        # c2 상태는 QUEUED로 안전하게 보존되어야 함
        assert c2.status == TaskStatus.QUEUED

        window.close()


def test_delete_requested_single_emission_without_recursion(
    app, mock_vod_info_factory, tmp_path
):
    """[결함 3] 카드 삭제 시 delete_requested가 정확히 1회만 방출되고 순환 재귀가 발생하지 않는지 검증."""
    with patch(
        "chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available", return_value=True
    ):
        window = MainWindow()
        c1 = TaskCardWidget(
            "https://chzzk.naver.com/video/v_single_del",
            status=TaskStatus.READY,
            vod_info=mock_vod_info_factory("v_single_del"),
            parent=window,
        )
        c1.custom_download_dir = tmp_path
        window.task_list_widget.add_task_card(c1)
        c1.trigger_start_download()

        emitted_count = 0

        def _count():
            nonlocal emitted_count
            emitted_count += 1

        c1.delete_requested.connect(_count)
        c1.delete_requested.emit()

        assert emitted_count == 1
        window.close()


def test_negative_waiting_position_clamping(app):
    """[결함 4] set_waiting_position에 음수가 전달되어도 UI에 -1번이 노출되지 않는지 검증."""
    card = TaskCardWidget("https://chzzk.naver.com/video/123", status=TaskStatus.QUEUED)
    card.set_waiting_position(-1)
    assert "-1" not in card.status_label.text()
    assert (
        card.status_label.text() == "대기 중..."
        or "대기 중" in card.status_label.text()
    )
    card.deleteLater()


def test_task_manager_progress_cache_cleanup_on_completion(app):
    """[결함 5] report_completed, report_failed, report_stopped 호출 시 _last_progress_time 캐시 정리 검증."""
    from chzzk_downloader.core.task_manager import TaskManager
    from chzzk_downloader.core.task_models import TaskProgress, TaskSpec

    tm = TaskManager(max_concurrent_vod=3)
    spec1 = TaskSpec("t1", "https://url/1")
    spec2 = TaskSpec("t2", "https://url/2")
    spec3 = TaskSpec("t3", "https://url/3")

    tm.add_task(spec1)
    tm.add_task(spec2)
    tm.add_task(spec3)

    tm.report_progress("t1", TaskProgress("t1", percentage=50.0))
    tm.report_progress("t2", TaskProgress("t2", percentage=50.0))
    tm.report_progress("t3", TaskProgress("t3", percentage=50.0))

    assert "t1" in tm._last_progress_time
    assert "t2" in tm._last_progress_time
    assert "t3" in tm._last_progress_time

    tm.report_completed("t1", "/path/1")
    tm.report_failed("t2", "NetworkError", "msg")
    tm.report_stopped("t3")

    assert "t1" not in tm._last_progress_time
    assert "t2" not in tm._last_progress_time
    assert "t3" not in tm._last_progress_time


def test_defect_stop_download_on_completed_causes_desync(app, tmp_path):
    """[2차 결함 1] COMPLETED 상태인 카드에 trigger_stop_download 호출 시 거부 및 상태 일치 검증."""
    window = MainWindow()
    info = VodInfo("123", "Title", "Streamer", "", 100, [VodFormatInfo("1080p", "1080p", 60)])
    card = TaskCardWidget("https://chzzk.naver.com/video/123", status=TaskStatus.READY, vod_info=info, parent=window)
    window.task_list_widget.add_task_card(card)

    with patch("chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available", return_value=True):
        card.trigger_start_download()

    window.task_manager.report_completed("123", str(tmp_path / "123.mp4"))
    assert card.status == TaskStatus.COMPLETED
    assert window.task_manager.get_task_status("123") == TaskStatus.COMPLETED

    with patch("chzzk_downloader.gui.task_card.ask_confirm_dialog", return_value=True):
        res = card.trigger_stop_download()

    assert res is False
    assert card.status == TaskStatus.COMPLETED
    assert window.task_manager.get_task_status("123") == TaskStatus.COMPLETED
    window.close()


def test_defect_trigger_start_download_without_ready_guard(app):
    """[2차 결함 2] READY가 아닌 상태(DOWNLOADING, QUEUED)에서 trigger_start_download 호출 시 차단 검증."""
    window = MainWindow()
    info = VodInfo("123", "Title", "Streamer", "", 100, [VodFormatInfo("1080p", "1080p", 60)])
    card = TaskCardWidget("https://chzzk.naver.com/video/123", status=TaskStatus.READY, vod_info=info, parent=window)
    window.task_list_widget.add_task_card(card)

    with patch("chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available", return_value=True):
        assert card.trigger_start_download() is True
        assert card.status == TaskStatus.DOWNLOADING

        res = card.trigger_start_download()
        assert res is False
    window.close()


def test_defect_remove_task_card_releases_slot_in_task_manager(app):
    """[2차 결함 3] remove_task_card 직접 호출 시에도 TaskManager 슬롯이 회수되는지 검증."""
    window = MainWindow()
    info = VodInfo("123", "Title", "Streamer", "", 100, [VodFormatInfo("1080p", "1080p", 60)])
    card = TaskCardWidget("https://chzzk.naver.com/video/123", status=TaskStatus.READY, vod_info=info, parent=window)
    window.task_list_widget.add_task_card(card)

    with patch("chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available", return_value=True):
        card.trigger_start_download()

    assert "123" in window.task_manager.get_running_vod_tasks()

    window.task_list_widget.remove_task_card(card)

    assert "123" not in window.task_manager.get_running_vod_tasks()
    window.close()


def test_defect_redownload_resets_task_manager(app):
    """[2차 결함 4] 재다운로드 확인 시 TaskManager.reset_task가 호출되어 상태가 초기화되는지 검증."""
    window = MainWindow()
    info = VodInfo("123", "Title", "Streamer", "", 100, [VodFormatInfo("1080p", "1080p", 60)])
    card = TaskCardWidget("https://chzzk.naver.com/video/123", status=TaskStatus.READY, vod_info=info, parent=window)
    window.task_list_widget.add_task_card(card)

    with patch("chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available", return_value=True):
        card.trigger_start_download()

    window.task_manager.report_completed("123", "dummy.mp4")
    assert window.task_manager.get_task_status("123") == TaskStatus.COMPLETED

    window.url_input.setText("https://chzzk.naver.com/video/123")
    with patch.object(window, "_confirm_redownload_dialog", return_value=True):
        with patch.object(window, "_start_vod_check"):
            window._on_download_clicked()

    assert card.status == TaskStatus.ANALYZING
    assert window.task_manager.get_task_status("123") == TaskStatus.READY
    window.close()


def test_defect_stale_waiting_position_cleared_on_queue_updated(app):
    """[2차 결함 5] pos <= 0 발생 시 on_queue_updated에서 대기 순번 문구가 정리되는지 검증."""
    window = MainWindow()
    info = VodInfo("123", "Title", "Streamer", "", 100, [VodFormatInfo("1080p", "1080p", 60)])
    card = TaskCardWidget("https://chzzk.naver.com/video/123", status=TaskStatus.QUEUED, vod_info=info, parent=window)
    card.set_waiting_position(5)
    window.task_list_widget.add_task_card(card)
    assert "5번" in card.status_label.text()

    window._on_queue_updated(0, 0, 0)

    assert "5번" not in card.status_label.text()
    window.close()

