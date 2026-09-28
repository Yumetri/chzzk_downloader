"""적대적 코드 리뷰에서 도출된 동시성 결함 및 엣지 케이스 재현 테스트 모듈.

검증 항목 (1차 및 2차 감사 전수 반영):
1. 슬롯 도난(Slot Hijacking) 및 큐 기아(Starvation) 방어 (원자적 슬롯 승계)
2. Task ID 중복 등록 시 유령 작업(Ghost Task)으로 인한 영구 슬롯 누수 방어 (멱등성 가드)
3. 연속 실패 시 동기식 이벤트 캐스케이드 재귀 폭사(RecursionError) 방어
4. reorder_task 락 누락 및 음수 인덱스(-2) 방어
5. reset_task 시 슬롯 회수 후 대기열 후속 작업 승계 보장
6. 완료/실패 작업 remove_task 및 _last_progress_time 메모리 누수 방어
7. get_task_spec 공개 API 및 세분화된 실패 상태(FAILED_INVALID, FAILED_LOGIN_REQUIRED) 매핑
8. [2차 감사 결함 1] 멀티스레드 동시 보고 시 이벤트 디스패처 IndexError 및 이벤트 유실 방어
9. [2차 감사 결함 3] 미등록/중복 report_* 호출 시 유령 슬롯 부정 승계 차단
10. [2차 감사 결함 2] cancel_task와 remove_task의 역할 분리 및 task_removed 시그널 중복 방출(Double-emit) 방지
11. [2차 감사 결함 5] 제거된 태스크의 지연 report_progress 시그널 방출 차단 및 캐시 누수 방지
12. [2차 감사 결함 8] TaskSpec frozen 불변성 보장 (외부 변조 방지)
13. [2차 감사 결함 9] reorder_task 동일 위치(0->0) 재배치 시 불필요한 시그널 방출 스킵
"""

import concurrent.futures
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from chzzk_downloader.core.task_manager import TaskManager
from chzzk_downloader.core.task_models import TaskProgress, TaskSpec, TaskStatus


def _make_spec(task_id: str, title: str = "Test Video", is_live: bool = False) -> TaskSpec:
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


def test_defect1_slot_hijacking_prevention() -> None:
    """결함 1: task_completed 핸들러에서 새 작업을 추가해도 대기열 1순위가 슬롯을 먼저 승계해야 함."""
    mgr = TaskManager(max_concurrent_vod=1)
    spec_a = _make_spec("A")
    spec_b = _make_spec("B")
    spec_c = _make_spec("C")

    mgr.add_task(spec_a)  # A 실행 중 (1/1)
    mgr.add_task(spec_b)  # B는 대기열(QUEUED) 1순위

    mgr.signals.task_completed.connect(lambda tid, path: mgr.add_task(spec_c))

    mgr.report_completed("A", "path/A.mp4")

    assert mgr.get_task_status("B") == TaskStatus.DOWNLOADING
    assert mgr.get_task_status("C") == TaskStatus.QUEUED
    assert mgr.get_running_vod_tasks() == ["B"]


def test_defect2_idempotency_prevents_ghost_slot_leak() -> None:
    """결함 2: 동일 Task ID 중복 등록 시 유령 작업으로 인한 영구 슬롯 누수 방어."""
    mgr = TaskManager(max_concurrent_vod=1)
    spec_a = _make_spec("A")

    status1 = mgr.add_task(spec_a)
    assert status1 == TaskStatus.DOWNLOADING

    status2 = mgr.add_task(spec_a)
    assert status2 == TaskStatus.DOWNLOADING
    assert len(mgr.get_queued_vod_tasks()) == 0

    mgr.report_completed("A", "path/A.mp4")
    assert mgr.get_task_status("A") == TaskStatus.COMPLETED
    assert len(mgr.get_running_vod_tasks()) == 0

    spec_b = _make_spec("B")
    status_b = mgr.add_task(spec_b)
    assert status_b == TaskStatus.DOWNLOADING
    assert mgr.get_running_vod_tasks() == ["B"]


def test_defect3_cascade_failure_no_recursion_error() -> None:
    """결함 3: 대기열 내 작업들의 연속 실패 발생 시 콜스택 초과(RecursionError) 없이 안전 처리."""
    mgr = TaskManager(max_concurrent_vod=1)

    for i in range(1200):
        mgr.add_task(_make_spec(f"task-{i}"))

    def on_status_changed(tid: str, old_s: TaskStatus, new_s: TaskStatus) -> None:
        if new_s == TaskStatus.DOWNLOADING:
            mgr.report_failed(tid, "NetworkError", "Connection refused")

    mgr.signals.task_status_changed.connect(on_status_changed)

    mgr.report_failed("task-0", "InitialError", "Failed")

    assert len(mgr.get_queued_vod_tasks()) == 0
    assert len(mgr.get_running_vod_tasks()) == 0


def test_defect4_reorder_race_condition_no_negative_index() -> None:
    """결함 4: reorder 도중 작업이 dequeue되더라도 음수 인덱스(-2)가 방출되지 않아야 함."""
    mgr = TaskManager(max_concurrent_vod=1)
    mgr.add_task(_make_spec("A"))  # running
    mgr.add_task(_make_spec("B"))  # queued pos 1
    mgr.add_task(_make_spec("C"))  # queued pos 2

    reordered_signals: list[tuple[str, int, int]] = []
    mgr.signals.task_reordered.connect(
        lambda tid, oi, ni: reordered_signals.append((tid, oi, ni))
    )

    orig_reorder = mgr._queue.reorder

    def race_hook(task_id: str, new_idx: int) -> bool:
        res = orig_reorder(task_id, new_idx)
        mgr.report_completed("A", "file.mp4")
        return res

    mgr._queue.reorder = race_hook  # type: ignore

    mgr.reorder_task("B", 0)

    for _tid, old_i, new_i in reordered_signals:
        assert old_i >= 0
        assert new_i >= 0


def test_defect5_reset_task_schedules_next_queued_task() -> None:
    """결함 5: 실행 중인 작업을 reset할 경우 슬롯이 반환되고 대기 작업이 자동 승계되어야 함."""
    mgr = TaskManager(max_concurrent_vod=1)
    mgr.add_task(_make_spec("A"))  # running
    mgr.add_task(_make_spec("B"))  # queued pos 1

    status_changes: list[tuple[str, TaskStatus, TaskStatus]] = []
    mgr.signals.task_status_changed.connect(
        lambda tid, os, ns: status_changes.append((tid, os, ns))
    )

    mgr.reset_task("A")

    assert mgr.get_task_status("A") == TaskStatus.READY
    assert mgr.get_task_status("B") == TaskStatus.DOWNLOADING
    assert mgr.get_running_vod_tasks() == ["B"]


def test_defect6_remove_task_cleans_memory_and_cache() -> None:
    """결함 6: 완료/실패된 작업 remove_task 시 _specs, _statuses, _last_progress_time 완전 정리."""
    mgr = TaskManager(max_concurrent_vod=1)
    mgr.add_task(_make_spec("A"))
    mgr.report_progress("A", TaskProgress(task_id="A", percentage=50.0))
    mgr.report_completed("A", "file.mp4")

    ok = mgr.remove_task("A")
    assert ok is True
    assert mgr.get_task_status("A") is None
    assert mgr.get_task_spec("A") is None
    assert "A" not in mgr._last_progress_time


def test_defect7_get_task_spec_and_granular_failed_status() -> None:
    """결함 7: get_task_spec 조회 및 에러 유형에 따른 세부 상태(FAILED_INVALID, FAILED_LOGIN_REQUIRED) 매핑."""
    mgr = TaskManager(max_concurrent_vod=2)
    spec_inv = _make_spec("inv")
    spec_login = _make_spec("login")

    mgr.add_task(spec_inv)
    mgr.add_task(spec_login)

    retrieved = mgr.get_task_spec("inv")
    assert retrieved is not None
    assert retrieved.task_id == "inv"

    mgr.report_failed("login", "LoginRequiredError", "Adult verification needed")
    assert mgr.get_task_status("login") == TaskStatus.FAILED_LOGIN_REQUIRED

    mgr.report_failed("inv", "VodNotFoundError", "404 Not Found")
    assert mgr.get_task_status("inv") == TaskStatus.FAILED_INVALID


def test_defect8_concurrent_multithreaded_event_dispatching(qtbot) -> None:
    """2차 감사 결함 1: 멀티스레드에서 동시 report_* 호출 시 IndexError나 이벤트 유실 없이 안전해야 함."""
    num_tasks = 20
    mgr = TaskManager(max_concurrent_vod=num_tasks)
    completed_events: list[tuple[str, str]] = []
    mgr.signals.task_completed.connect(lambda tid, path: completed_events.append((tid, path)))

    for i in range(num_tasks):
        mgr.add_task(_make_spec(f"vod-{i}"))

    def worker_finish(task_id: str) -> None:
        mgr.report_completed(task_id, f"C:/downloads/{task_id}.mp4")

    # 10개 스레드가 동시에 완료 보고를 쏟아냄
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker_finish, f"vod-{i}") for i in range(num_tasks)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    qtbot.waitUntil(lambda: len(completed_events) == num_tasks, timeout=2000)
    assert len(completed_events) == num_tasks
    assert len(mgr.get_running_vod_tasks()) == 0


def test_defect9_ghost_report_guard() -> None:
    """2차 감사 결함 3: 미등록 또는 이미 완료/중지된 작업의 report 호출 시 슬롯 부정 승계 차단."""
    mgr = TaskManager(max_concurrent_vod=1)
    mgr.add_task(_make_spec("real-1"))
    mgr.add_task(_make_spec("real-2"))  # real-2는 QUEUED

    # 1. 미등록 태스크 완료 보고 시 무시
    ok = mgr.report_completed("ghost-task", "dummy_path")
    assert ok is False
    assert mgr.get_task_status("ghost-task") is None
    # real-2가 부정 승계되지 않고 여전히 QUEUED여야 함
    assert mgr.get_task_status("real-2") == TaskStatus.QUEUED

    # 2. real-1 정상 완료
    assert mgr.report_completed("real-1", "path.mp4") is True
    assert mgr.get_task_status("real-2") == TaskStatus.DOWNLOADING

    # 3. 이미 완료된 real-1에 대해 지연된 report_failed 중복 보고 시 무시
    assert mgr.report_failed("real-1", "LateError", "Late error") is False
    assert mgr.get_task_status("real-1") == TaskStatus.COMPLETED


def test_defect10_cancel_and_remove_separation() -> None:
    """2차 감사 결함 2: cancel_task는 STOPPED 전이만 수행하고, remove_task가 완전 제거 및 1회 시그널 방출."""
    mgr = TaskManager(max_concurrent_vod=1)
    removed_signals: list[str] = []
    mgr.signals.task_removed.connect(lambda tid: removed_signals.append(tid))

    mgr.add_task(_make_spec("vod-run"))
    assert mgr.get_task_status("vod-run") == TaskStatus.DOWNLOADING

    # cancel_task는 작업을 중지(STOPPED)시키되, 목록/specs에서 즉시 영구 삭제하지 않음 (UI가 닫기 전까지 보존)
    assert mgr.cancel_task("vod-run") is True
    assert mgr.get_task_status("vod-run") == TaskStatus.STOPPED
    assert mgr.get_task_spec("vod-run") is not None
    # cancel_task 자체는 removed 시그널을 방출하지 않음
    assert len(removed_signals) == 0

    # 사용자가 카드 닫기를 누를 때 remove_task 호출 -> 완전히 제거되고 1회 removed 시그널 방출
    assert mgr.remove_task("vod-run") is True
    assert len(removed_signals) == 1
    assert mgr.get_task_status("vod-run") is None
    assert mgr.get_task_spec("vod-run") is None

    # 이미 제거된 작업에 대해 재호출 시 False 반환 (중복 removed 방출 방지)
    assert mgr.remove_task("vod-run") is False
    assert len(removed_signals) == 1


def test_defect11_progress_on_removed_task_no_leak() -> None:
    """2차 감사 결함 5: 제거된 태스크의 지연 report_progress 시그널 방출 차단 및 캐시 누수 방지."""
    mgr = TaskManager()
    mgr.add_task(_make_spec("vod-1"))
    mgr.remove_task("vod-1")

    progress_signals: list[tuple[str, TaskProgress]] = []
    mgr.signals.task_progress_updated.connect(lambda tid, p: progress_signals.append((tid, p)))

    # 제거된 태스크에 대해 지연 프로그레스 보고
    prog = TaskProgress(task_id="vod-1", percentage=50.0)
    mgr.report_progress("vod-1", prog)

    # 시그널이 방출되지 않고 캐시에 남지 않아야 함
    assert len(progress_signals) == 0
    assert "vod-1" not in mgr._last_progress_time


def test_defect12_reorder_noop_no_signal() -> None:
    """2차 감사 결함 9: 동일 위치 reorder 호출 시 불필요한 시그널 방출 스킵."""
    mgr = TaskManager(max_concurrent_vod=1)
    mgr.add_task(_make_spec("run"))
    mgr.add_task(_make_spec("q1"))
    mgr.add_task(_make_spec("q2"))

    reordered_signals: list[tuple[str, int, int]] = []
    mgr.signals.task_reordered.connect(lambda tid, oi, ni: reordered_signals.append((tid, oi, ni)))

    # q1은 이미 0번 인덱스임 -> 0번으로 재배치 요청 시 no-op
    ok = mgr.reorder_task("q1", 0)
    assert ok is True
    assert len(reordered_signals) == 0


def test_defect13_task_spec_frozen_immutability() -> None:
    """2차 감사 결함 8: TaskSpec 불변성(frozen) 검증."""
    spec = _make_spec("A")
    with pytest.raises(FrozenInstanceError):
        spec.title = "Altered Title"  # type: ignore
