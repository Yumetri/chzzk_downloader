"""TaskManager (중앙 작업 관리자) 단위 테스트 모듈."""

import time
from pathlib import Path

from PyQt6.QtCore import QObject

from chzzk_downloader.core.task_manager import TaskManager
from chzzk_downloader.core.task_models import TaskProgress, TaskSpec, TaskStatus


def _make_spec(
    task_id: str, title: str = "Test Video", is_live: bool = False
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        video_url=f"https://chzzk.naver.com/video/{task_id}",
        is_live=is_live,
        title=title,
        streamer="Streamer",
        selected_quality="1080p",
        selected_ext="mp4",
        save_path=Path(f"C:/downloads/{task_id}.mp4"),
    )


class SignalRecorder(QObject):
    """TaskManager 시그널 수신 기록기."""

    def __init__(self, manager: TaskManager) -> None:
        super().__init__()
        self.added: list[tuple[str, TaskSpec]] = []
        self.status_changes: list[tuple[str, TaskStatus, TaskStatus]] = []
        self.completed: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str, str, str]] = []
        self.removed: list[str] = []
        self.progress_updates: list[tuple[str, TaskProgress]] = []
        self.reordered: list[tuple[str, int, int]] = []
        self.queue_updates: list[tuple[int, int, int]] = []

        manager.signals.task_added.connect(
            lambda tid, spec: self.added.append((tid, spec))
        )
        manager.signals.task_status_changed.connect(
            lambda tid, old_s, new_s: self.status_changes.append((tid, old_s, new_s))
        )
        manager.signals.task_completed.connect(
            lambda tid, path: self.completed.append((tid, path))
        )
        manager.signals.task_failed.connect(
            lambda tid, et, msg, tb: self.failed.append((tid, et, msg, tb))
        )
        manager.signals.task_removed.connect(lambda tid: self.removed.append(tid))
        manager.signals.task_progress_updated.connect(
            lambda tid, prog: self.progress_updates.append((tid, prog))
        )
        manager.signals.task_reordered.connect(
            lambda tid, old_i, new_i: self.reordered.append((tid, old_i, new_i))
        )
        manager.signals.queue_updated.connect(
            lambda r_vod, q_vod, r_live: self.queue_updates.append(
                (r_vod, q_vod, r_live)
            )
        )


def test_vod_slots_concurrency_and_queuing(qtbot) -> None:
    """기본 3개 슬롯 한도 초과 시 QUEUED 상태 진입 검증."""
    manager = TaskManager(max_concurrent_vod=3)
    recorder = SignalRecorder(manager)

    # 3개 작업 추가 -> 모두 즉시 DOWNLOADING 슬롯 할당
    for i in range(1, 4):
        spec = _make_spec(f"vod-{i}")
        status = manager.add_task(spec)
        assert status == TaskStatus.DOWNLOADING
        assert manager.get_task_status(f"vod-{i}") == TaskStatus.DOWNLOADING

    assert len(manager.get_running_vod_tasks()) == 3
    assert len(manager.get_queued_vod_tasks()) == 0

    # 4번째 VOD 작업 추가 -> 슬롯 만석이므로 QUEUED 상태 진입
    spec4 = _make_spec("vod-4")
    status4 = manager.add_task(spec4)
    assert status4 == TaskStatus.QUEUED
    assert manager.get_task_status("vod-4") == TaskStatus.QUEUED
    assert len(manager.get_queued_vod_tasks()) == 1
    assert manager.get_waiting_position("vod-4") == 1

    # 마지막 큐 갱신 시그널 확인 (running_vod=3, queued_vod=1, running_live=0)
    assert recorder.queue_updates[-1] == (3, 1, 0)


def test_slot_auto_succession_on_completion(qtbot) -> None:
    """실행 중 작업 완료 시 대기 중이던 최우선 작업이 슬롯을 자동 승계하는지 검증."""
    manager = TaskManager(max_concurrent_vod=2)
    recorder = SignalRecorder(manager)

    spec1 = _make_spec("vod-1")
    spec2 = _make_spec("vod-2")
    spec3 = _make_spec("vod-3")

    manager.add_task(spec1)
    manager.add_task(spec2)
    manager.add_task(spec3)  # vod-3은 QUEUED 대기

    assert manager.get_task_status("vod-3") == TaskStatus.QUEUED

    # vod-1 작업 완료 보고
    manager.report_completed("vod-1", "C:/downloads/vod-1.mp4")

    assert manager.get_task_status("vod-1") == TaskStatus.COMPLETED
    # vod-3이 자동으로 DOWNLOADING으로 전이되어야 함
    assert manager.get_task_status("vod-3") == TaskStatus.DOWNLOADING
    assert len(manager.get_running_vod_tasks()) == 2
    assert len(manager.get_queued_vod_tasks()) == 0

    # 상태 전이 시그널에 (vod-3, QUEUED, DOWNLOADING) 기록 확인
    assert (
        "vod-3",
        TaskStatus.QUEUED,
        TaskStatus.DOWNLOADING,
    ) in recorder.status_changes


def test_live_lane_isolation_unlimited(qtbot) -> None:
    """실시간 라이브 작업은 VOD 슬롯 만석 여부와 관계없이 VIP 독립 실행되는지 검증."""
    manager = TaskManager(max_concurrent_vod=2)
    recorder = SignalRecorder(manager)

    manager.add_task(_make_spec("vod-1"))
    manager.add_task(_make_spec("vod-2"))
    # VOD 슬롯 만석

    # 실시간 라이브 작업 추가
    live_spec = _make_spec("live-1", title="Live Stream", is_live=True)
    status = manager.add_task(live_spec)

    assert status == TaskStatus.DOWNLOADING
    assert manager.get_task_status("live-1") == TaskStatus.DOWNLOADING
    assert len(manager.get_running_live_tasks()) == 1
    assert len(manager.get_running_vod_tasks()) == 2
    assert recorder.queue_updates[-1] == (2, 0, 1)


def test_remove_queued_task(qtbot) -> None:
    """대기열에 있는 작업 삭제 시 큐에서 안전하게 제거되고 후속 대기 순번이 앞당겨지는지 검증."""
    manager = TaskManager(max_concurrent_vod=1)
    recorder = SignalRecorder(manager)

    manager.add_task(_make_spec("vod-1"))  # 실행
    manager.add_task(_make_spec("vod-2"))  # 대기 1번
    manager.add_task(_make_spec("vod-3"))  # 대기 2번

    assert manager.get_waiting_position("vod-2") == 1
    assert manager.get_waiting_position("vod-3") == 2

    # 대기 중인 작업에 대해 cancel_task는 허용되지 않음 (QUEUED는 STOPPED로 전이되지 않음)
    assert manager.cancel_task("vod-2") is False

    # vod-2 완전 제거 -> task_removed 시그널 방출 및 대기열 제외
    removed = manager.remove_task("vod-2")
    assert removed is True
    assert "vod-2" in recorder.removed
    assert manager.get_task_status("vod-2") is None
    assert manager.get_waiting_position("vod-2") == -1
    # vod-3이 대기 1번으로 앞당겨져야 함
    assert manager.get_waiting_position("vod-3") == 1


def test_reorder_queued_tasks(qtbot) -> None:
    """대기열 순서 변경 시 reordered 시그널 및 대기 순번이 정상 갱신되는지 검증."""
    manager = TaskManager(max_concurrent_vod=1)
    recorder = SignalRecorder(manager)

    manager.add_task(_make_spec("vod-running"))
    manager.add_task(_make_spec("vod-q1"))
    manager.add_task(_make_spec("vod-q2"))
    manager.add_task(_make_spec("vod-q3"))

    assert manager.get_waiting_position("vod-q3") == 3

    # vod-q3을 0번(대기열 맨 앞)으로 이동
    ok = manager.reorder_task("vod-q3", 0)
    assert ok is True
    assert manager.get_waiting_position("vod-q3") == 1
    assert manager.get_waiting_position("vod-q1") == 2
    assert manager.get_waiting_position("vod-q2") == 3
    assert recorder.reordered[-1] == ("vod-q3", 2, 0)


def test_progress_throttling_100ms(qtbot) -> None:
    """고주파 프로그레스 호출 시 100ms 스로틀링이 적용되어 UI 시그널 폭주를 막는지 검증."""
    manager = TaskManager(max_concurrent_vod=1, progress_throttle_interval_sec=0.1)
    recorder = SignalRecorder(manager)

    manager.add_task(_make_spec("vod-1"))

    # 짧은 시간(예: 10ms 간격으로 10회 연속 보고)
    for i in range(10):
        prog = TaskProgress(
            task_id="vod-1",
            downloaded_bytes=1000 * i,
            total_bytes=10000,
            percentage=float(i * 10),
            speed_bytes_sec=50000.0,
            speed_str="50 KB/s",
            eta_seconds=10 - i,
            eta_str=f"00:00:{10 - i:02d}",
        )
        manager.report_progress("vod-1", prog)
        time.sleep(0.005)

    # 10회 고주파 호출 중 100ms 스로틀링으로 인해 방출 횟수는 10회보다 현저히 적어야 함 (보통 1~2회)
    assert 1 <= len(recorder.progress_updates) < 5
