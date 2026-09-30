"""TaskQueue (스레드 세이프 작업 대기열) 단위 테스트 모듈."""

import concurrent.futures
from pathlib import Path

from chzzk_downloader.core.task_models import TaskSpec
from chzzk_downloader.core.task_queue import TaskQueue


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


def test_enqueue_and_dequeue_fifo() -> None:
    queue = TaskQueue()
    assert len(queue) == 0
    assert queue.is_empty()

    spec1 = _make_spec("task-1")
    spec2 = _make_spec("task-2")
    spec3 = _make_spec("task-3")

    pos1 = queue.enqueue(spec1)
    pos2 = queue.enqueue(spec2)
    pos3 = queue.enqueue(spec3)

    assert pos1 == 1
    assert pos2 == 2
    assert pos3 == 3
    assert len(queue) == 3
    assert not queue.is_empty()

    out1 = queue.dequeue()
    assert out1 is not None and out1.task_id == "task-1"
    assert len(queue) == 2

    out2 = queue.dequeue()
    assert out2 is not None and out2.task_id == "task-2"
    assert len(queue) == 1

    out3 = queue.dequeue()
    assert out3 is not None and out3.task_id == "task-3"
    assert len(queue) == 0
    assert queue.dequeue() is None


def test_remove_task() -> None:
    queue = TaskQueue()
    spec1 = _make_spec("task-1")
    spec2 = _make_spec("task-2")
    spec3 = _make_spec("task-3")

    queue.enqueue(spec1)
    queue.enqueue(spec2)
    queue.enqueue(spec3)

    # 중간 항목 제거
    removed = queue.remove("task-2")
    assert removed is True
    assert len(queue) == 2
    assert queue.get_waiting_position("task-2") == -1
    assert queue.get_waiting_position("task-3") == 2

    # 존재하지 않는 항목 제거
    assert queue.remove("non-existent") is False
    assert len(queue) == 2


def test_reorder_task() -> None:
    queue = TaskQueue()
    spec1 = _make_spec("task-1")
    spec2 = _make_spec("task-2")
    spec3 = _make_spec("task-3")

    queue.enqueue(spec1)
    queue.enqueue(spec2)
    queue.enqueue(spec3)

    # task-3을 0번(맨 앞)으로 이동
    ok = queue.reorder("task-3", 0)
    assert ok is True
    snapshot = queue.get_snapshot()
    assert [s.task_id for s in snapshot] == ["task-3", "task-1", "task-2"]
    assert queue.get_waiting_position("task-3") == 1
    assert queue.get_waiting_position("task-1") == 2
    assert queue.get_waiting_position("task-2") == 3


def test_reorder_out_of_bounds_clamping() -> None:
    queue = TaskQueue()
    spec1 = _make_spec("task-1")
    spec2 = _make_spec("task-2")
    spec3 = _make_spec("task-3")

    queue.enqueue(spec1)
    queue.enqueue(spec2)
    queue.enqueue(spec3)

    # 음수 인덱스는 0번(맨 앞)으로 클램핑
    assert queue.reorder("task-2", -5) is True
    assert [s.task_id for s in queue.get_snapshot()] == ["task-2", "task-1", "task-3"]

    # 초과 인덱스는 마지막 위치로 클램핑
    assert queue.reorder("task-2", 999) is True
    assert [s.task_id for s in queue.get_snapshot()] == ["task-1", "task-3", "task-2"]

    # 존재하지 않는 태스크
    assert queue.reorder("unknown", 0) is False


def test_get_snapshot_immutability() -> None:
    queue = TaskQueue()
    spec1 = _make_spec("task-1")
    queue.enqueue(spec1)

    snapshot = queue.get_snapshot()
    assert len(snapshot) == 1

    # 외부에서 반환된 리스트를 수정해도 내부 큐는 변하지 않아야 함
    snapshot.append(_make_spec("fake"))
    assert len(queue) == 1
    assert len(queue.get_snapshot()) == 1


def test_multithreaded_concurrency_safety() -> None:
    queue = TaskQueue()
    num_threads = 10
    items_per_thread = 50

    def worker(thread_idx: int) -> None:
        for i in range(items_per_thread):
            task_id = f"t-{thread_idx}-{i}"
            spec = _make_spec(task_id)
            queue.enqueue(spec)
            queue.get_waiting_position(task_id)
            if i % 3 == 0:
                queue.reorder(task_id, 0)
            if i % 5 == 0:
                queue.dequeue()
            if i % 7 == 0:
                queue.remove(task_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, t) for t in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    # 스레드 작업 후 큐 상태 조회 시 예외나 크래시가 없어야 함
    snapshot = queue.get_snapshot()
    assert len(queue) == len(snapshot)
    for idx, s in enumerate(snapshot):
        assert queue.get_waiting_position(s.task_id) == idx + 1
