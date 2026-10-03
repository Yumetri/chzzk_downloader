"""T0113. VOD 취소 및 실패 재시도(이어받기)와 완료 확정 검증 테스트.

- TaskManager retry_task: 슬롯 여유 시 DOWNLOADING 전이, 만석 시 QUEUED 전이
- TaskManager retry_task: 실행 중/대기 중/완료 상태의 중복 재시도 방어
- TaskManager complete_task: STOPPED 작업의 COMPLETED 확정 및 시그널 방출
- TaskCardWidget: STOPPED 및 FAILED_DOWNLOAD 상태의 4번 위치 컨트롤 및 2번 위치 재시도 버튼 노출
- TaskCardWidget: 4번 위치 [🔄] 및 2번 위치 [🔄] 클릭 시 retry_requested 시그널 방출
- TaskCardWidget: 4번 위치 [✓] 클릭 시 complete_requested 시그널 방출
- TaskCardWidget: 우클릭 컨텍스트 메뉴(다시 다운로드, 완료 확정, URL 복사) 액션 검증
- MainWindow: 카드 재시도 요청 수신 시 기존 명세 유지 및 이어받기 파이프라인 트리거
- VodDownloadWorker: 중단/실패 시 유효 미디어 및 .ytdl 메타데이터 보존 검증
"""

import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

from chzzk_downloader.core.task_manager import TaskManager
from chzzk_downloader.core.task_models import TaskProgress, TaskSpec, TaskStatus
from chzzk_downloader.core.ytdlp import VodFormatInfo, VodInfo
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.task_card import TaskCardWidget
from chzzk_downloader.gui.workers import VodDownloadWorker


@pytest.fixture
def temp_settings_env(tmp_path):
    """임시 디렉터리에 격리된 settings.json 환경을 제공하는 fixture."""
    from chzzk_downloader.core.settings_manager import (
        set_custom_settings_path,
        update_current_settings,
    )

    test_settings_file = tmp_path / ".chzzk_downloader" / "settings.json"
    set_custom_settings_path(test_settings_file)
    update_current_settings(
        download_dir=str(tmp_path / "downloads"),
        default_quality="최고 화질",
        file_extension=".mp4",
        vod_auto_download=False,
    )
    yield test_settings_file
    set_custom_settings_path(None)


# ============================================================================
# 1. TaskManager 코어 스케줄러 재시도 및 완료 확정 단위 테스트
# ============================================================================


def test_retry_task_transitions_to_downloading_when_slot_available():
    """슬롯 여유가 있을 때 retry_task 호출 시 작업이 즉시 DOWNLOADING 상태로 전이되는지 검증."""
    manager = TaskManager(max_concurrent_vod=2)
    spec = TaskSpec(
        task_id="vod_101",
        video_url="https://chzzk.naver.com/video/101",
        title="테스트 방송",
        selected_quality="1080p",
    )
    manager.add_task(spec)
    manager.cancel_task(spec.task_id)
    assert manager.get_task_status(spec.task_id) == TaskStatus.STOPPED

    status_changes: list[tuple[str, TaskStatus, TaskStatus]] = []
    manager.signals.task_status_changed.connect(
        lambda tid, old_s, new_s: status_changes.append((tid, old_s, new_s))
    )

    ok = manager.retry_task(spec.task_id)
    assert ok is True
    assert manager.get_task_status(spec.task_id) == TaskStatus.DOWNLOADING
    assert ("vod_101", TaskStatus.STOPPED, TaskStatus.DOWNLOADING) in status_changes


def test_retry_task_transitions_to_queued_when_slots_are_full():
    """슬롯이 꽉 찼을 때 retry_task 호출 시 작업이 QUEUED 상태로 대기열에 진입하는지 검증."""
    manager = TaskManager(max_concurrent_vod=1)
    spec1 = TaskSpec(task_id="vod_1", video_url="https://chzzk.naver.com/video/1")
    spec2 = TaskSpec(task_id="vod_2", video_url="https://chzzk.naver.com/video/2")

    manager.add_task(spec1)
    assert manager.get_task_status(spec1.task_id) == TaskStatus.DOWNLOADING

    # spec1 취소하여 STOPPED 상태로 전환
    manager.cancel_task(spec1.task_id)
    assert manager.get_task_status(spec1.task_id) == TaskStatus.STOPPED

    # spec2를 추가하여 1개뿐인 슬롯을 점유 (DOWNLOADING)
    manager.add_task(spec2)
    assert manager.get_task_status(spec2.task_id) == TaskStatus.DOWNLOADING

    # 슬롯이 꽉 찬 상태에서 spec1 재시도 -> QUEUED 상태 진입
    ok = manager.retry_task(spec1.task_id)
    assert ok is True
    assert manager.get_task_status(spec1.task_id) == TaskStatus.QUEUED
    assert manager.get_waiting_position(spec1.task_id) == 1


def test_retry_task_rejects_duplicate_or_completed_tasks():
    """이미 실행 중이거나 대기 중이거나 완료된 작업에 대한 재시도 요청은 안전하게 거부되는지 검증."""
    manager = TaskManager(max_concurrent_vod=2)
    spec = TaskSpec(task_id="vod_test", video_url="https://chzzk.naver.com/video/99")
    manager.add_task(spec)
    assert manager.get_task_status(spec.task_id) == TaskStatus.DOWNLOADING

    # 1. DOWNLOADING 상태 재시도 거부
    assert manager.retry_task(spec.task_id) is False

    # 2. COMPLETED 상태 재시도 거부
    manager.report_completed(spec.task_id, "/downloads/vod_test.mp4")
    assert manager.get_task_status(spec.task_id) == TaskStatus.COMPLETED
    assert manager.retry_task(spec.task_id) is False

    # 3. 미등록 작업 거부
    assert manager.retry_task("non_existent_task") is False


def test_complete_task_transitions_stopped_task_to_completed():
    """STOPPED 상태의 작업에 대해 complete_task 호출 시 COMPLETED로 확정되고 시그널이 방출되는지 검증."""
    manager = TaskManager(max_concurrent_vod=2)
    spec = TaskSpec(
        task_id="vod_stop_to_complete",
        video_url="https://chzzk.naver.com/video/55",
        save_path="/downloads/test.mp4",
    )
    manager.add_task(spec)
    manager.cancel_task(spec.task_id)
    assert manager.get_task_status(spec.task_id) == TaskStatus.STOPPED

    completed_events: list[tuple[str, str]] = []
    manager.signals.task_completed.connect(
        lambda tid, path: completed_events.append((tid, path))
    )

    ok = manager.complete_task(spec.task_id, "/downloads/test.mp4")
    assert ok is True
    assert manager.get_task_status(spec.task_id) == TaskStatus.COMPLETED
    assert ("vod_stop_to_complete", "/downloads/test.mp4") in completed_events


def test_complete_task_transitions_failed_download_and_login_required_to_completed():
    """FAILED_DOWNLOAD 및 FAILED_LOGIN_REQUIRED 상태의 작업에 대해 complete_task 호출 시 COMPLETED로 확정되는지 검증."""
    manager = TaskManager(max_concurrent_vod=2)

    # 1. FAILED_DOWNLOAD 상태 작업
    spec1 = TaskSpec(
        task_id="vod_failed_download",
        video_url="https://chzzk.naver.com/video/56",
        save_path="/downloads/test1.mp4",
    )
    manager.add_task(spec1)
    manager.report_failed(spec1.task_id, "DownloadError", "네트워크 단절")
    assert manager.get_task_status(spec1.task_id) == TaskStatus.FAILED_DOWNLOAD

    ok1 = manager.complete_task(spec1.task_id, "/downloads/test1.mp4")
    assert ok1 is True
    assert manager.get_task_status(spec1.task_id) == TaskStatus.COMPLETED

    # 2. FAILED_LOGIN_REQUIRED 상태 작업
    spec2 = TaskSpec(
        task_id="vod_failed_login",
        video_url="https://chzzk.naver.com/video/57",
        save_path="/downloads/test2.mp4",
    )
    manager.add_task(spec2)
    manager.report_failed(spec2.task_id, "HTTPError", "401 Unauthorized")
    assert manager.get_task_status(spec2.task_id) == TaskStatus.FAILED_LOGIN_REQUIRED

    ok2 = manager.complete_task(spec2.task_id, "/downloads/test2.mp4")
    assert ok2 is True
    assert manager.get_task_status(spec2.task_id) == TaskStatus.COMPLETED


# ============================================================================
# 2. TaskCardWidget 재시도 컨트롤 및 시그널 GUI 단위 테스트
# ============================================================================


def test_task_card_stopped_controls_visibility_and_signals(qtbot, tmp_path):
    """STOPPED 상태에서 4번 위치 stopped_container와 2번 위치 retry_btn이 노출되고 시그널을 방출하는지 검증."""
    card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/100", video_no="100")
    qtbot.addWidget(card)
    card.show()

    card.last_progress = TaskProgress(
        task_id="100", percentage=42.5, downloaded_bytes=42500, total_bytes=100000
    )
    card.set_task_status(TaskStatus.STOPPED)

    # 1. 4번 위치 stopped_container 가시성 및 정지 진행률 값 검증
    assert card.stopped_container.isVisible() is True
    assert card.stopped_progress_bar.value() == 42
    assert card.stopped_pct_label.text() == "42%"

    # 1-1. 유효 미디어 파일 부재 시 [✓ 완료 확정] 버튼은 아예 숨겨져 있어야 함 (Red 검증)
    assert card.stopped_complete_btn.isVisible() is False

    # 2. 2번 위치 호버 시 retry_btn 노출 검증
    card.enterEvent(None)
    assert card.retry_btn.isVisible() is True

    # 3. 4번 위치 [🔄] 클릭 시 retry_requested 시그널 방출 검증
    with qtbot.waitSignal(card.retry_requested, timeout=1000) as blocker:
        card.stopped_retry_btn.click()
    assert blocker.args == ["100"]

    # 4. 유효 미디어 파일 주입 시 [✓ 완료 확정] 버튼 노출 및 툴팁 "완료 확정" 검증
    test_media = tmp_path / "valid_stopped_media.mp4"
    test_media.write_bytes(b"downloaded stream")
    card.target_path = test_media
    card.set_task_status(TaskStatus.READY)
    card.set_task_status(TaskStatus.STOPPED)

    assert card.stopped_complete_btn.isVisible() is True
    assert card.stopped_complete_btn.toolTip() == "완료 확정"

    # 4-1. 4번 위치 [✓] 클릭 시 complete_requested 시그널 방출 검증
    with qtbot.waitSignal(card.complete_requested, timeout=1000) as blocker:
        card.stopped_complete_btn.click()
    assert blocker.args == ["100"]

    # 5. 2번 위치 [🔄] 클릭 시 retry_requested 시그널 방출 검증
    with qtbot.waitSignal(card.retry_requested, timeout=1000) as blocker:
        card.retry_btn.click()
    assert blocker.args == ["100"]


def test_task_card_failed_download_shows_retry_and_complete_when_file_exists(
    qtbot, tmp_path
):
    """FAILED_DOWNLOAD 상태에서 유효 파일이 있으면 [🔄]와 [✓] 버튼이 모두 활성화되는지 검증."""
    card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/200", video_no="200")
    qtbot.addWidget(card)
    card.show()

    test_file = tmp_path / "test_partial.mp4"
    test_file.write_bytes(b"some media data")
    card.target_path = test_file

    card.set_task_status(TaskStatus.FAILED_DOWNLOAD)

    assert card.failed_retry_btn.isVisible() is True
    assert card.failed_complete_btn.isVisible() is True

    with qtbot.waitSignal(card.retry_requested, timeout=1000) as blocker:
        card.failed_retry_btn.click()
    assert blocker.args == ["200"]


def test_task_card_context_menu_actions(qtbot, tmp_path):
    """우클릭 컨텍스트 메뉴에서 다시 다운로드, 완료 확정, URL 복사 액션이 정상 작동하는지 검증."""
    card = TaskCardWidget(raw_url="https://chzzk.naver.com/video/300", video_no="300")
    qtbot.addWidget(card)
    card.set_task_status(TaskStatus.STOPPED)

    # 1. URL 복사 메서드 검증
    card.copy_url_to_clipboard()
    clipboard = QApplication.clipboard()
    if clipboard:
        assert clipboard.text() == "https://chzzk.naver.com/video/300"

    # 2. 유효 파일 부재 시 상태 검증
    assert card.has_local_media_file is False

    # 3. 유효 파일 주입 후 상태 검증
    test_file = tmp_path / "valid_300.mp4"
    test_file.write_bytes(b"media stream")
    card.target_path = test_file
    assert card.has_local_media_file is True

    # 4. 재시도 트리거 검증
    with qtbot.waitSignal(card.retry_requested, timeout=1000) as blocker:
        card.trigger_retry()
    assert blocker.args == ["300"]

    # 5. 완료 확정 트리거 검증
    with qtbot.waitSignal(card.complete_requested, timeout=1000) as blocker:
        card.trigger_complete()
    assert blocker.args == ["300"]


# ============================================================================
# 3. MainWindow 통합 재시도 및 완료 확정 파이프라인 테스트
# ============================================================================


def test_main_window_retry_flow_resumes_stopped_task(
    qtbot, temp_settings_env, monkeypatch
):
    """MainWindow에서 카드의 재시도 요청을 수신하여 TaskManager를 통해 안전하게 재개하는지 검증."""
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "_start_vod_download", lambda tid: None)

    vod_info = VodInfo(
        video_no="777",
        video_title="이어받기 테스트 방송",
        channel_name="스트리머A",
        duration=3600,
        thumbnail_url="",
        formats=[VodFormatInfo(format_id="1080p", resolution="1080p")],
    )
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/777",
        video_no="777",
        vod_info=vod_info,
        status=TaskStatus.READY,
    )
    window.task_list_widget.add_task_card(card)

    spec = card.get_task_spec()
    window.task_manager.add_task(spec)
    window.task_manager.cancel_task(spec.task_id)
    assert window.task_manager.get_task_status(spec.task_id) == TaskStatus.STOPPED

    # 재시도 요청 방출 시뮬레이션
    card.retry_requested.emit(spec.task_id)

    # 슬롯 여유가 있으므로 DOWNLOADING 상태로 즉시 복귀해야 함
    qtbot.waitUntil(
        lambda: (
            window.task_manager.get_task_status(spec.task_id) == TaskStatus.DOWNLOADING
        ),
        timeout=2000,
    )
    assert card.status == TaskStatus.DOWNLOADING


def test_main_window_complete_flow_finalizes_stopped_task(
    qtbot, temp_settings_env, tmp_path
):
    """MainWindow에서 카드의 완료 확정 요청을 수신하여 작업을 COMPLETED로 확정하는지 검증."""
    window = MainWindow()
    qtbot.addWidget(window)

    dummy_media = tmp_path / "downloads" / "complete_sample.mp4"
    dummy_media.parent.mkdir(parents=True, exist_ok=True)
    dummy_media.write_bytes(b"completed valid video data")

    vod_info = VodInfo(
        video_no="888",
        video_title="완료 확정 방송",
        channel_name="스트리머B",
        duration=1800,
        thumbnail_url="",
        formats=[VodFormatInfo(format_id="1080p", resolution="1080p")],
    )
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/888",
        video_no="888",
        vod_info=vod_info,
        status=TaskStatus.READY,
    )
    card.target_path = dummy_media
    window.task_list_widget.add_task_card(card)

    spec = card.get_task_spec()
    window.task_manager.add_task(spec)
    window.task_manager.cancel_task(spec.task_id)
    assert window.task_manager.get_task_status(spec.task_id) == TaskStatus.STOPPED

    # 완료 확정 요청 방출 시뮬레이션
    card.complete_requested.emit(spec.task_id)

    qtbot.waitUntil(
        lambda: (
            window.task_manager.get_task_status(spec.task_id) == TaskStatus.COMPLETED
        ),
        timeout=2000,
    )
    assert card.status == TaskStatus.COMPLETED


def test_main_window_complete_flow_blocks_and_warns_when_file_missing(
    qtbot, temp_settings_env
):
    """디스크에 유효한 미디어 파일(>0B)이 존재하지 않는 경우 완료 확정이 안전하게 차단되고 경고 토스트가 발생하는지 검증."""
    window = MainWindow()
    qtbot.addWidget(window)

    vod_info = VodInfo(
        video_no="889",
        video_title="파일 없는 취소 방송",
        channel_name="스트리머C",
        duration=1800,
        formats=[VodFormatInfo(format_id="1080p", resolution="1080p")],
    )
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/889",
        video_no="889",
        vod_info=vod_info,
        status=TaskStatus.READY,
    )
    # 디스크에 생성되지 않은 가상 경로 지정
    card.target_path = Path("/non_existent_folder/missing.mp4")
    window.task_list_widget.add_task_card(card)

    spec = card.get_task_spec()
    window.task_manager.add_task(spec)
    window.task_manager.cancel_task(spec.task_id)
    assert window.task_manager.get_task_status(spec.task_id) == TaskStatus.STOPPED

    # 파일이 없는 상태에서 완료 확정 요청 시도
    card.complete_requested.emit(spec.task_id)

    # 상태가 COMPLETED로 잘못 전이되지 않고 STOPPED로 유지되어야 함
    assert window.task_manager.get_task_status(spec.task_id) == TaskStatus.STOPPED
    assert card.status == TaskStatus.STOPPED


def test_main_window_complete_flow_finalizes_failed_download_card(
    qtbot, temp_settings_env, tmp_path
):
    """MainWindow에서 FAILED_DOWNLOAD 상태의 카드에 유효 파일이 있을 때 완료 확정 시 COMPLETED로 정상 전이되는지 검증."""
    window = MainWindow()
    qtbot.addWidget(window)

    dummy_media = tmp_path / "downloads" / "failed_then_completed.mp4"
    dummy_media.parent.mkdir(parents=True, exist_ok=True)
    dummy_media.write_bytes(b"valid partial media stream")

    vod_info = VodInfo(
        video_no="890",
        video_title="실패 후 완료 확정 방송",
        channel_name="스트리머D",
        duration=2400,
        thumbnail_url="",
        formats=[VodFormatInfo(format_id="1080p", resolution="1080p")],
    )
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/890",
        video_no="890",
        vod_info=vod_info,
        status=TaskStatus.READY,
    )
    card.target_path = dummy_media
    window.task_list_widget.add_task_card(card)

    spec = card.get_task_spec()
    window.task_manager.add_task(spec)
    window.task_manager.report_failed(spec.task_id, "DownloadError", "일시적 연결 끊김")
    assert (
        window.task_manager.get_task_status(spec.task_id) == TaskStatus.FAILED_DOWNLOAD
    )

    # 카드의 완료 확정 요청 시뮬레이션
    card.complete_requested.emit(spec.task_id)

    qtbot.waitUntil(
        lambda: (
            window.task_manager.get_task_status(spec.task_id) == TaskStatus.COMPLETED
        ),
        timeout=2000,
    )
    assert card.status == TaskStatus.COMPLETED


# ============================================================================
# 4. 워커 미디어 및 메타데이터 보존 단위 검증
# ============================================================================


def test_worker_cleanup_preserves_valid_media_and_ytdl_file(tmp_path):
    """워커의 cleanup_partial_files(delete_media=False) 호출 시 유효 미디어와 .ytdl 파일이 보존되는지 검증."""
    media_file = tmp_path / "video.mp4"
    media_file.write_bytes(b"partially downloaded valid video stream")

    ytdl_file = tmp_path / "video.mp4.ytdl"
    ytdl_file.write_bytes(b'{"downloaded_bytes": 1024}')

    empty_part_file = tmp_path / "video.mp4.part"
    empty_part_file.write_bytes(b"")

    spec = TaskSpec(
        task_id="preserve_test",
        video_url="https://chzzk.naver.com/video/999",
        save_path=media_file,
    )
    worker = VodDownloadWorker(spec)
    worker.created_paths.add(empty_part_file)

    # delete_media=False로 정리 실행
    worker.cleanup_partial_files(delete_media=False)

    # 1. 0바이트 임시 파일은 삭제
    assert empty_part_file.exists() is False

    # 2. 유효한 미디어 파일(> 0B) 및 이어받기용 .ytdl 메타데이터는 보존
    assert media_file.exists() is True
    assert media_file.stat().st_size > 0
    assert ytdl_file.exists() is True


def test_worker_cleanup_preserves_unrelated_neighbor_files(tmp_path):
    """워커 정리 시 동일 디렉터리의 다른 동영상 및 무관한 파일들이 절대 삭제되지 않는지 엄격한 음성 단언 검증."""
    # 정리 대상 파일군
    target_media = tmp_path / "target_vod.mp4"
    target_media.write_bytes(b"target partially downloaded")
    target_part = tmp_path / "target_vod.mp4.part"
    target_part.write_bytes(b"")

    # 절대 삭제되면 안 되는 무관한 이웃 파일들
    neighbor_media = tmp_path / "neighbor_movie.mp4"
    neighbor_media.write_bytes(b"another finished vod")
    neighbor_ytdl = tmp_path / "neighbor_movie.mp4.ytdl"
    neighbor_ytdl.write_bytes(b"important metadata")
    neighbor_part = tmp_path / "neighbor_movie.mp4.part"
    neighbor_part.write_bytes(b"another active download")
    unrelated_text = tmp_path / "readme.txt"
    unrelated_text.write_text("critical notes", encoding="utf-8")

    spec = TaskSpec(
        task_id="neighbor_guard_test",
        video_url="https://chzzk.naver.com/video/1000",
        save_path=target_media,
    )
    worker = VodDownloadWorker(spec)
    worker.created_paths.add(target_part)

    # 정리 실행
    worker.cleanup_partial_files(delete_media=False)

    # 대상 정리 결과 검증
    assert target_part.exists() is False
    assert target_media.exists() is True

    # 음성 단언: 이웃 파일들은 단 하나도 훼손되지 않고 온전히 유지되어야 함
    assert neighbor_media.exists() is True
    assert neighbor_media.read_bytes() == b"another finished vod"
    assert neighbor_ytdl.exists() is True
    assert neighbor_part.exists() is True
    assert unrelated_text.exists() is True


# ============================================================================
# 5. 동시성 및 레이스 컨디션 적대적 방어 검증
# ============================================================================


def test_retry_rapid_spam_requests_strictly_bounded_by_slot_limit():
    """사용자가 재시도 버튼을 고속으로 10회 연속 연타하더라도 슬롯 수 한도를 초과하지 않고 멱등성을 유지하는지 검증."""
    manager = TaskManager(max_concurrent_vod=2)
    spec = TaskSpec(
        task_id="spam_test",
        video_url="https://chzzk.naver.com/video/555",
    )
    manager.add_task(spec)
    manager.cancel_task(spec.task_id)
    assert manager.get_task_status(spec.task_id) == TaskStatus.STOPPED

    results: list[bool] = []
    # 10회 연속 연타 시도
    for _ in range(10):
        results.append(manager.retry_task(spec.task_id))

    # 첫 번째 재시도만 성공(True)하고 나머지 9회는 중복 요청으로 거부(False)되어야 함
    assert results[0] is True
    assert all(r is False for r in results[1:])
    assert manager.get_task_status(spec.task_id) == TaskStatus.DOWNLOADING

    # 동시성 단언: 실행 중인 작업 수는 슬롯 수(2) 이하 및 정확히 1개여야 함
    running_vods = manager.get_running_vod_tasks()
    assert len(running_vods) <= 2
    assert len(running_vods) == 1


class ControlledRetryWorker(QThread):
    """테스트에서 시작/중지 타이밍을 통제할 수 있는 테스트용 워커."""

    progress_updated = pyqtSignal(TaskProgress)
    download_finished = pyqtSignal(str, str)
    download_failed = pyqtSignal(str, str, str, str)
    download_stopped = pyqtSignal(str)

    def __init__(self, spec: TaskSpec, parent=None) -> None:
        super().__init__(parent)
        self.task_spec = spec
        self.task_id = spec.task_id
        self.is_cancelled = False
        self.run_started = threading.Event()
        self.release_finish = threading.Event()

    def cancel(self) -> None:
        self.is_cancelled = True

    def run(self) -> None:
        self.run_started.set()
        self.release_finish.wait(timeout=5.0)
        if self.is_cancelled:
            self.download_stopped.emit(self.task_id)
        else:
            self.download_finished.emit(self.task_id, str(self.task_spec.save_path))


def test_retry_while_previous_worker_running_defers_and_hands_over(
    qtbot, temp_settings_env
):
    """이전 워커가 아직 정리 중(isRunning)인 상태에서 재시도 요청이 올 경우 중복 기동을 방지하고 바통 대기 등록을 검증."""
    window = MainWindow()
    qtbot.addWidget(window)

    created_workers: list[ControlledRetryWorker] = []

    def _worker_factory(spec: TaskSpec, parent=None) -> ControlledRetryWorker:
        w = ControlledRetryWorker(spec, parent=parent)
        created_workers.append(w)
        return w

    vod_info = VodInfo(
        video_no="999",
        video_title="바통 터치 방송",
        channel_name="스트리머D",
        duration=3600,
        formats=[VodFormatInfo(format_id="1080p", resolution="1080p")],
    )
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/999",
        video_no="999",
        vod_info=vod_info,
        status=TaskStatus.READY,
    )
    window.task_list_widget.add_task_card(card)
    spec = card.get_task_spec()

    with patch(
        "chzzk_downloader.gui.main_window.VodDownloadWorker",
        side_effect=_worker_factory,
    ):
        # 1. 초기 다운로드 시작 -> 첫 번째 워커 생성 및 실행
        window.task_manager.add_task(spec)
        assert len(created_workers) == 1
        worker1 = created_workers[0]
        assert worker1.run_started.wait(timeout=2.0)

        # 2. 작업 중지 요청 (워커1은 아직 release_finish 대기 중이라 isRunning 상태)
        window.task_list_widget.card_stop_requested.emit(spec.task_id)
        assert worker1.isRunning()

        # 3. 이전 워커가 살아있는 동안 카드에서 재시도 요청
        card.retry_requested.emit(spec.task_id)

        # 4. 안전 방어 단언: 이전 워커가 살아있는 동안에는 즉시 새 워커가 중복 생성되지 않아야 함
        assert len(created_workers) == 1

        # 5. 이전 워커 완전 종료 허용 -> 정리 완료 후 바통을 이어받아 2번째 워커가 자동 시작됨
        worker1.release_finish.set()
        qtbot.waitUntil(lambda: len(created_workers) == 2, timeout=2000)
        worker2 = created_workers[1]
        assert worker2.run_started.wait(timeout=2.0)
        worker2.release_finish.set()
        worker2.cancel()
        qtbot.waitUntil(lambda: not worker2.isRunning(), timeout=2000)


def test_failed_login_required_preserves_ytdl_and_allows_one_click_retry(
    qtbot, tmp_path
):
    """401 등으로 FAILED_LOGIN_REQUIRED 상태가 되었을 때 .ytdl 및 미디어가 보존되고 원클릭 [🔄] 재시도가 가능한지 검증."""
    media_file = tmp_path / "protected_vod.mp4"
    media_file.write_bytes(b"downloaded part stream")
    ytdl_file = tmp_path / "protected_vod.mp4.ytdl"
    ytdl_file.write_bytes(b'{"session_resume": true}')

    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15310191",
        video_no="15310191",
    )
    qtbot.addWidget(card)
    card.show()
    card.target_path = media_file

    # FAILED_LOGIN_REQUIRED 상태 설정
    card.set_task_status(TaskStatus.FAILED_LOGIN_REQUIRED)

    # 1. 4번 위치 컨트롤에 [Z], [🗨️!], [🍪], [N], [🔄] 노출 검증
    assert card.auth_container.isVisible() is True
    assert card.chzzk_badge.isVisible() is True
    assert card.error_info_btn.isVisible() is True
    assert card.cookie_btn.isVisible() is True
    assert card.login_btn.isVisible() is True
    assert card.failed_retry_btn.isVisible() is True

    # 2. 4번 위치 [🔄] 클릭 시 재시도 시그널 방출 검증
    with qtbot.waitSignal(card.retry_requested, timeout=1000) as blocker:
        card.failed_retry_btn.click()
    assert blocker.args == ["15310191"]

    # 3. 디스크의 유효 미디어 및 .ytdl 파일 보존 검증
    assert media_file.exists() is True
    assert media_file.stat().st_size > 0
    assert ytdl_file.exists() is True
