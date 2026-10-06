"""스레드 세이프 작업 대기열(TaskQueue) 모듈 (RFC #87)."""

import threading

from chzzk_downloader.core.task_models import TaskSpec


class TaskQueue:
    """스레드 안전한(Thread-Safe) 우선순위 작업 대기열."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: list[TaskSpec] = []

    def enqueue(self, spec: TaskSpec) -> int:
        """대기열 끝에 작업을 추가하고 대기 순번(1부터 시작)을 반환합니다."""
        with self._lock:
            self._items.append(spec)
            return len(self._items)

    def dequeue(self) -> TaskSpec | None:
        """대기열 맨 앞(1순위)의 작업을 꺼내 반환합니다. 비어있으면 None을 반환합니다."""
        with self._lock:
            if not self._items:
                return None
            return self._items.pop(0)

    def remove(self, task_id: str) -> bool:
        """대기열에서 특정 task_id의 작업을 찾아 제거합니다. 제거 성공 시 True를 반환합니다."""
        with self._lock:
            for idx, item in enumerate(self._items):
                if item.task_id == task_id:
                    self._items.pop(idx)
                    return True
            return False

    def reorder(self, task_id: str, new_index: int) -> bool:
        """대기열 내 특정 작업의 위치를 재배치합니다.

        - new_index가 0 미만이면 0으로 자동 클램핑됩니다.
        - new_index가 대기열 길이를 초과하면 마지막 위치로 자동 클램핑됩니다.
        - 작업이 대기열에 존재하지 않으면 False를 반환합니다.
        """
        with self._lock:
            found_idx = -1
            target_item: TaskSpec | None = None
            for idx, item in enumerate(self._items):
                if item.task_id == task_id:
                    found_idx = idx
                    target_item = item
                    break

            if found_idx == -1 or target_item is None:
                return False

            self._items.pop(found_idx)

            # 경계값 자동 클램핑
            clamped_idx = max(0, min(new_index, len(self._items)))
            self._items.insert(clamped_idx, target_item)
            return True

    def get_waiting_position(self, task_id: str) -> int:
        """특정 작업의 대기 순번(1부터 시작)을 반환합니다. 대기열에 없으면 -1을 반환합니다."""
        with self._lock:
            for idx, item in enumerate(self._items):
                if item.task_id == task_id:
                    return idx + 1
            return -1

    def get_snapshot(self) -> list[TaskSpec]:
        """현재 대기열의 불변 스냅샷(복사본 리스트)을 반환합니다."""
        with self._lock:
            return list(self._items)

    def is_empty(self) -> bool:
        """대기열이 비어있는지 여부를 반환합니다."""
        with self._lock:
            return len(self._items) == 0

    def __len__(self) -> int:
        """현재 대기열의 작업 수를 반환합니다."""
        with self._lock:
            return len(self._items)
