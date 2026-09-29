"""중앙 작업 관리자(TaskManager) 모듈 (RFC #87).

견고성 보강:
- Thread-Local 디스패처: 스레드별 이벤트 큐 격리로 멀티스레드 동시 보고 시 IndexError 및 이벤트 유실 원천 차단
- 멱등성 및 상태 가드: report_* 계열 메서드에 미등록 태스크 및 DOWNLOADING 외 상태의 중복/부정 슬롯 승계 원천 차단
- cancel_task와 remove_task의 역할 분리: 취소는 STOPPED 전이, 삭제는 remove_task가 전담하여 task_removed 중복 방출(Double-emit) 방지
- report_progress 유효성 가드: 소멸/제거된 작업의 지연 프로그레스 방출 및 캐시 누수 방지
- TaskSpec/TaskProgress frozen 불변성 및 RLock 교착 상태 방지
- reorder_task No-op 스킵 (불필요한 0->0 시그널 방지)
"""

import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

from chzzk_downloader.core.task_models import TaskProgress, TaskSpec, TaskStatus
from chzzk_downloader.core.task_queue import TaskQueue


class TaskManagerSignals(QObject):
    """UI와 코어 간 8대 비동기 시그널 통신 규약 (RFC #87)."""

    # 1. 작업 생명주기 및 상태 변화 시그널
    task_added = pyqtSignal(str, object)  # (task_id, TaskSpec)
    task_status_changed = pyqtSignal(
        str, object, object
    )  # (task_id, old_status, new_status)
    task_completed = pyqtSignal(str, str)  # (task_id, final_file_path)
    task_failed = pyqtSignal(str, str, str, str)  # (task_id, err_type, msg, traceback)
    task_removed = pyqtSignal(str)  # (task_id)

    # 2. 고주파 프로그레스 시그널 (UI 60fps 보장을 위해 100ms 스로틀링 적용)
    task_progress_updated = pyqtSignal(str, object)  # (task_id, TaskProgress)

    # 3. 큐 및 스케줄러 상태 시그널
    task_reordered = pyqtSignal(str, int, int)  # (task_id, old_index, new_index)
    queue_updated = pyqtSignal(int, int, int)  # (running_vod, queued_vod, running_live)


class TaskManager:
    """중앙 관제탑 작업 관리자 및 슬롯 스케줄러."""

    def __init__(
        self,
        max_concurrent_vod: int = 3,
        progress_throttle_interval_sec: float = 0.1,
    ) -> None:
        self.max_concurrent_vod = max_concurrent_vod
        self.progress_throttle_interval_sec = progress_throttle_interval_sec

        self.signals = TaskManagerSignals()
        self._queue = TaskQueue()

        self._lock = threading.RLock()
        self._specs: dict[str, TaskSpec] = {}
        self._statuses: dict[str, TaskStatus] = {}

        self._running_vod_ids: set[str] = set()
        self._running_live_ids: set[str] = set()
        self._last_progress_time: dict[str, float] = {}

        # 스레드별 재귀 방어 큐 및 디스패처 플래그 (스레드 간 간섭 및 레이스 원천 차단)
        self._thread_local = threading.local()

    def _get_thread_event_queue(self) -> list[tuple]:
        if not hasattr(self._thread_local, "event_queue"):
            self._thread_local.event_queue = []
        return self._thread_local.event_queue

    def _enqueue_and_dispatch_events(self, events: list[tuple]) -> None:
        """이벤트를 스레드 로컬 큐에 넣고 순차 방출하여 스택 오버플로우와 멀티스레드 경합을 동시 방어합니다."""
        t_queue = self._get_thread_event_queue()
        t_queue.extend(events)

        if getattr(self._thread_local, "is_dispatching", False):
            return

        self._thread_local.is_dispatching = True
        try:
            while t_queue:
                event = t_queue.pop(0)
                event_type = event[0]
                args = event[1:]

                if event_type == "status_changed":
                    self.signals.task_status_changed.emit(*args)
                elif event_type == "completed":
                    self.signals.task_completed.emit(*args)
                elif event_type == "failed":
                    self.signals.task_failed.emit(*args)
                elif event_type == "removed":
                    self.signals.task_removed.emit(*args)
                elif event_type == "added":
                    self.signals.task_added.emit(*args)
                elif event_type == "reordered":
                    self.signals.task_reordered.emit(*args)
                elif event_type == "queue_updated":
                    self.signals.queue_updated.emit(*args)
        finally:
            self._thread_local.is_dispatching = False

    def add_task(self, spec: TaskSpec) -> TaskStatus:
        """작업을 등록하고 창구 여유에 따라 즉시 실행 또는 큐에 대기시킵니다.

        - 멱등성 가드: 이미 실행/대기 중인 task_id의 중복 등록을 안전하게 방어합니다.
        """
        events: list[tuple] = []
        initial_status: TaskStatus

        with self._lock:
            # 멱등성 검사: 이미 존재하는 작업인 경우 중복 적재 방어
            if spec.task_id in self._specs:
                curr_status = self._statuses.get(spec.task_id)
                if curr_status in (TaskStatus.DOWNLOADING, TaskStatus.QUEUED):
                    return curr_status

            is_new_task = spec.task_id not in self._specs
            old_status = self._statuses.get(spec.task_id, TaskStatus.READY)
            self._specs[spec.task_id] = spec

            # 1. 실시간 라이브는 VOD 슬롯과 완전히 분리된 무제한 VIP 독립 창구로 즉시 실행
            if spec.is_live:
                self._running_live_ids.add(spec.task_id)
                self._statuses[spec.task_id] = TaskStatus.DOWNLOADING
                initial_status = TaskStatus.DOWNLOADING
            else:
                # 2. 일반 VOD: 동시 다운로드 창구(기본 3슬롯) 여유 검사
                if len(self._running_vod_ids) < self.max_concurrent_vod:
                    self._running_vod_ids.add(spec.task_id)
                    self._statuses[spec.task_id] = TaskStatus.DOWNLOADING
                    initial_status = TaskStatus.DOWNLOADING
                else:
                    self._queue.enqueue(spec)
                    self._statuses[spec.task_id] = TaskStatus.QUEUED
                    initial_status = TaskStatus.QUEUED

            if is_new_task:
                events.append(("added", spec.task_id, spec))
            events.append(("status_changed", spec.task_id, old_status, initial_status))

            r_vod = len(self._running_vod_ids)
            q_vod = len(self._queue)
            r_live = len(self._running_live_ids)
            events.append(("queue_updated", r_vod, q_vod, r_live))

        self._enqueue_and_dispatch_events(events)
        return initial_status

    def report_completed(self, task_id: str, file_path: str) -> bool:
        """작업 완료를 보고하고 단일 락 내에서 원자적으로 슬롯을 회수 및 대기 작업을 승계합니다."""
        events: list[tuple] = []
        with self._lock:
            # 멱등성 가드: 등록되지 않았거나 DOWNLOADING 상태가 아닌 경우 보고 거부
            if task_id not in self._specs:
                return False
            if self._statuses.get(task_id) != TaskStatus.DOWNLOADING:
                return False

            self._running_vod_ids.discard(task_id)
            self._running_live_ids.discard(task_id)
            self._last_progress_time.pop(task_id, None)
            old_status = self._statuses.get(task_id)
            self._statuses[task_id] = TaskStatus.COMPLETED

            if old_status is not None:
                events.append(
                    ("status_changed", task_id, old_status, TaskStatus.COMPLETED)
                )
            events.append(("completed", task_id, file_path))

            # 원자적 슬롯 승계
            self._schedule_next_vod_locked(events)

            r_vod = len(self._running_vod_ids)
            q_vod = len(self._queue)
            r_live = len(self._running_live_ids)
            events.append(("queue_updated", r_vod, q_vod, r_live))

        self._enqueue_and_dispatch_events(events)
        return True

    def report_failed(
        self,
        task_id: str,
        err_type: str,
        msg: str,
        traceback_str: str = "",
    ) -> bool:
        """작업 실패를 보고하고 에러 유형에 따른 세분화된 상태 매핑 및 원자적 슬롯 승계를 수행합니다."""
        events: list[tuple] = []
        err_lower = (err_type + " " + msg).lower()

        # 세분화된 실패 상태 매핑
        if any(
            k in err_lower
            for k in (
                "login",
                "adult",
                "성인",
                "로그인",
                "인증",
                "401",
                "403",
                "unauthorized",
                "forbidden",
            )
        ):
            new_status = TaskStatus.FAILED_LOGIN_REQUIRED
        elif any(
            k in err_lower for k in ("notfound", "invalid", "잘못된", "비공개", "404")
        ):
            new_status = TaskStatus.FAILED_INVALID
        else:
            new_status = TaskStatus.FAILED_DOWNLOAD

        with self._lock:
            if task_id not in self._specs:
                return False
            if self._statuses.get(task_id) != TaskStatus.DOWNLOADING:
                return False

            self._running_vod_ids.discard(task_id)
            self._running_live_ids.discard(task_id)
            self._last_progress_time.pop(task_id, None)
            old_status = self._statuses.get(task_id)
            self._statuses[task_id] = new_status

            if old_status is not None:
                events.append(("status_changed", task_id, old_status, new_status))
            events.append(("failed", task_id, err_type, msg, traceback_str))

            # 원자적 슬롯 승계
            self._schedule_next_vod_locked(events)

            r_vod = len(self._running_vod_ids)
            q_vod = len(self._queue)
            r_live = len(self._running_live_ids)
            events.append(("queue_updated", r_vod, q_vod, r_live))

        self._enqueue_and_dispatch_events(events)
        return True

    def report_stopped(self, task_id: str) -> bool:
        """작업 중지를 보고하고 슬롯을 반환한 뒤 대기열 작업을 자동 승계합니다."""
        events: list[tuple] = []
        with self._lock:
            if task_id not in self._specs:
                return False
            if self._statuses.get(task_id) != TaskStatus.DOWNLOADING:
                return False

            self._running_vod_ids.discard(task_id)
            self._running_live_ids.discard(task_id)
            self._last_progress_time.pop(task_id, None)
            old_status = self._statuses.get(task_id)
            self._statuses[task_id] = TaskStatus.STOPPED

            if old_status is not None:
                events.append(
                    ("status_changed", task_id, old_status, TaskStatus.STOPPED)
                )

            # 원자적 슬롯 승계
            self._schedule_next_vod_locked(events)

            r_vod = len(self._running_vod_ids)
            q_vod = len(self._queue)
            r_live = len(self._running_live_ids)
            events.append(("queue_updated", r_vod, q_vod, r_live))

        self._enqueue_and_dispatch_events(events)
        return True

    def report_progress(self, task_id: str, progress: TaskProgress) -> None:
        """진행률 보고 시 100ms 스로틀링 및 유효성 가드를 적용합니다."""
        now = time.monotonic()
        with self._lock:
            if task_id not in self._specs:
                return
            if self._statuses.get(task_id) != TaskStatus.DOWNLOADING:
                return

            last_time = self._last_progress_time.get(task_id, 0.0)
            is_completed = progress.percentage >= 100.0
            if not is_completed and (
                now - last_time < self.progress_throttle_interval_sec
            ):
                return
            self._last_progress_time[task_id] = now

        self.signals.task_progress_updated.emit(task_id, progress)

    def cancel_task(self, task_id: str) -> bool:
        """대기열 작업 취소 또는 실행 중인 작업의 안전 중지를 처리합니다 (STOPPED 전이).

        - 주의: cancel_task는 작업을 중지(STOPPED)시키는 메서드이며, 영구 삭제(removed)는 remove_task가 담당합니다.
        """
        events: list[tuple] = []
        is_handled = False

        with self._lock:
            if task_id not in self._specs:
                return False

            curr_status = self._statuses.get(task_id)
            if curr_status == TaskStatus.QUEUED:
                self._queue.remove(task_id)
                self._statuses[task_id] = TaskStatus.STOPPED
                self._last_progress_time.pop(task_id, None)
                events.append(
                    ("status_changed", task_id, TaskStatus.QUEUED, TaskStatus.STOPPED)
                )
                is_handled = True
            elif curr_status == TaskStatus.DOWNLOADING:
                self._running_vod_ids.discard(task_id)
                self._running_live_ids.discard(task_id)
                self._statuses[task_id] = TaskStatus.STOPPED
                self._last_progress_time.pop(task_id, None)
                events.append(
                    (
                        "status_changed",
                        task_id,
                        TaskStatus.DOWNLOADING,
                        TaskStatus.STOPPED,
                    )
                )
                self._schedule_next_vod_locked(events)
                is_handled = True

            if is_handled:
                r_vod = len(self._running_vod_ids)
                q_vod = len(self._queue)
                r_live = len(self._running_live_ids)
                events.append(("queue_updated", r_vod, q_vod, r_live))

        if is_handled:
            self._enqueue_and_dispatch_events(events)
            return True
        return False

    def remove_task(self, task_id: str) -> bool:
        """작업을 관리자에서 완전히 제거하고 캐시를 정리하며 1회의 task_removed 시그널을 방출합니다."""
        events: list[tuple] = []
        with self._lock:
            if task_id not in self._specs and task_id not in self._statuses:
                return False

            was_running_vod = task_id in self._running_vod_ids
            self._specs.pop(task_id, None)
            self._statuses.pop(task_id, None)
            self._running_vod_ids.discard(task_id)
            self._running_live_ids.discard(task_id)
            self._queue.remove(task_id)
            self._last_progress_time.pop(task_id, None)

            events.append(("removed", task_id))
            if was_running_vod:
                self._schedule_next_vod_locked(events)

            r_vod = len(self._running_vod_ids)
            q_vod = len(self._queue)
            r_live = len(self._running_live_ids)
            events.append(("queue_updated", r_vod, q_vod, r_live))

        self._enqueue_and_dispatch_events(events)
        return True

    def reorder_task(self, task_id: str, new_index: int) -> bool:
        """대기 중인 작업의 대기 순서를 원자적으로 재배치하고, 위치 변동이 있을 때만 시그널을 방출합니다."""
        events: list[tuple] = []
        with self._lock:
            old_pos = self._queue.get_waiting_position(task_id)
            if old_pos == -1:
                return False

            old_idx = old_pos - 1
            ok = self._queue.reorder(task_id, new_index)
            if not ok:
                return False

            new_pos = self._queue.get_waiting_position(task_id)
            if new_pos == -1:
                return False

            new_idx = new_pos - 1
            # 위치 변동이 없는 No-op인 경우 불필요한 시그널 방출 스킵
            if old_idx != new_idx:
                events.append(("reordered", task_id, old_idx, new_idx))
                r_vod = len(self._running_vod_ids)
                q_vod = len(self._queue)
                r_live = len(self._running_live_ids)
                events.append(("queue_updated", r_vod, q_vod, r_live))

        if events:
            self._enqueue_and_dispatch_events(events)
        return True

    def reset_task(self, task_id: str) -> bool:
        """이전 세션 리소스를 정리하고 최신 환경설정을 반영하여 클린 리셋하며, 슬롯 반환 시 후속 작업을 승계합니다."""
        events: list[tuple] = []
        with self._lock:
            spec = self._specs.get(task_id)
            if not spec:
                return False

            old_status = self._statuses.get(task_id, TaskStatus.STOPPED)
            was_running_vod = task_id in self._running_vod_ids
            self._running_vod_ids.discard(task_id)
            self._running_live_ids.discard(task_id)
            self._queue.remove(task_id)
            self._statuses[task_id] = TaskStatus.READY
            self._last_progress_time.pop(task_id, None)

            events.append(("status_changed", task_id, old_status, TaskStatus.READY))

            if was_running_vod:
                self._schedule_next_vod_locked(events)

            r_vod = len(self._running_vod_ids)
            q_vod = len(self._queue)
            r_live = len(self._running_live_ids)
            events.append(("queue_updated", r_vod, q_vod, r_live))

        self._enqueue_and_dispatch_events(events)
        return True

    def _schedule_next_vod_locked(self, events: list[tuple]) -> None:
        """동일 락(_lock) 내부에서 호출되어 슬롯 여유만큼 대기열 최우선 VOD를 인출하고 슬롯을 즉시 점유합니다."""
        while len(self._running_vod_ids) < self.max_concurrent_vod:
            next_spec = self._queue.dequeue()
            if next_spec is None:
                break
            self._running_vod_ids.add(next_spec.task_id)
            old_s = self._statuses.get(next_spec.task_id, TaskStatus.QUEUED)
            self._statuses[next_spec.task_id] = TaskStatus.DOWNLOADING
            events.append(
                (
                    "status_changed",
                    next_spec.task_id,
                    old_s,
                    TaskStatus.DOWNLOADING,
                )
            )

    def get_task_spec(self, task_id: str) -> TaskSpec | None:
        """특정 작업의 명세(TaskSpec)를 반환합니다."""
        with self._lock:
            return self._specs.get(task_id)

    def get_task_status(self, task_id: str) -> TaskStatus | None:
        """특정 작업의 현재 상태를 반환합니다."""
        with self._lock:
            return self._statuses.get(task_id)

    def get_waiting_position(self, task_id: str) -> int:
        """특정 작업의 대기 순번(1부터 시작)을 반환합니다."""
        return self._queue.get_waiting_position(task_id)

    def get_running_vod_tasks(self) -> list[str]:
        """현재 실행 중인 VOD 작업 ID 목록을 반환합니다."""
        with self._lock:
            return list(self._running_vod_ids)

    def get_queued_vod_tasks(self) -> list[TaskSpec]:
        """현재 대기열에 대기 중인 VOD 작업 명세 목록을 반환합니다."""
        return self._queue.get_snapshot()

    def get_running_live_tasks(self) -> list[str]:
        """현재 실행 중인 라이브 작업 ID 목록을 반환합니다."""
        with self._lock:
            return list(self._running_live_ids)
