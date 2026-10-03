"""다운로드 워커 수명주기, 슬롯 반환, 안전 정리 단위 테스트."""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

from chzzk_downloader.core.task_models import TaskProgress, TaskSpec, TaskStatus
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.task_card import _delete_file_safely
from chzzk_downloader.gui.workers import VodDownloadWorker


@pytest.fixture
def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    return instance


class ControlledWorker(QThread):
    """테스트에서 시작/중지/종료 타이밍을 현실적으로 통제할 수 있는 가짜 워커."""

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
        self.cancel_received = threading.Event()
        self.release_finish = threading.Event()

    def cancel(self) -> None:
        self.is_cancelled = True
        self.cancel_received.set()

    def run(self) -> None:
        self.run_started.set()
        self.cancel_received.wait(timeout=5.0)
        if self.is_cancelled:
            self.download_stopped.emit(self.task_id)
            self.release_finish.wait(timeout=5.0)
        else:
            self.download_finished.emit(self.task_id, str(self.task_spec.save_path))


def test_stop_keeps_slot_until_worker_finished(app, qtbot):
    """중지 요청 후 worker.finished가 오기 전까지 슬롯을 유지하고 대기 작업을 시작하지 않는지 검증."""
    window = MainWindow()
    qtbot.addWidget(window)
    # 슬롯 제한을 1로 설정하여 슬롯 선반환 시 대기 작업이 즉시 시작되는 결함을 검출
    window.task_manager.max_concurrent_vod = 1

    created_workers: list[ControlledWorker] = []

    def _worker_factory(spec: TaskSpec, parent=None) -> ControlledWorker:
        w = ControlledWorker(spec, parent=parent)
        created_workers.append(w)
        return w

    spec1 = TaskSpec(
        task_id="t1", video_url="https://chzzk.naver.com/video/1", save_path="v1.mp4"
    )
    spec2 = TaskSpec(
        task_id="t2", video_url="https://chzzk.naver.com/video/2", save_path="v2.mp4"
    )

    with patch(
        "chzzk_downloader.gui.main_window.VodDownloadWorker",
        side_effect=_worker_factory,
    ):
        # 1. 작업 1 등록 -> 즉시 DOWNLOADING 및 워커 1 시작
        window.task_manager.add_task(spec1)
        assert len(created_workers) == 1
        worker1 = created_workers[0]
        assert worker1.run_started.wait(timeout=2.0)

        # 2. 작업 2 등록 -> 슬롯 만석(1)이므로 QUEUED
        window.task_manager.add_task(spec2)
        assert window.task_manager.get_task_status("t2") == TaskStatus.QUEUED

        # 3. 작업 1 중지 요청 (워커는 download_stopped 방출 후 아직 실행 중)
        window.task_list_widget.card_stop_requested.emit("t1")
        assert worker1.isRunning()

        # 4. 결함 검증 단언: 워커 1이 finished 되기 전까지는
        # - 작업 1이 슬롯(running_vod)을 계속 점유하고 있어야 함
        # - 작업 2가 슬롯을 가로채서 DOWNLOADING으로 승격되거나 새 워커를 시작하면 안 됨
        assert "t1" in window.task_manager.get_running_vod_tasks(), (
            "워커가 종료(finished)되기 전에는 running_vod 슬롯을 반환하지 않아야 합니다."
        )
        assert window.task_manager.get_task_status("t2") == TaskStatus.QUEUED, (
            "이전 워커가 실행 중인 동안 대기 작업이 시작되어서는 안 됩니다."
        )
        assert len(created_workers) == 1, (
            "이전 워커가 살아있는 동안 새 워커가 생성되지 않아야 합니다."
        )

        # 5. 워커 1 완전 종료 허용 -> 슬롯 반환 및 대기 작업 2 승계
        worker1.release_finish.set()
        qtbot.waitUntil(lambda: not worker1.isRunning(), timeout=2000)

        # 워커 1 종료 후 작업 2가 승계되어 실행됨
        qtbot.waitUntil(lambda: len(created_workers) == 2, timeout=2000)
        worker2 = created_workers[1]
        assert worker2.run_started.wait(timeout=2.0)
        worker2.release_finish.set()
        worker2.cancel()
        qtbot.waitUntil(lambda: not worker2.isRunning(), timeout=2000)

    window.close()


def test_running_workers_never_exceed_slot_limit(app, qtbot):
    """중지와 새 작업 시작을 반복해도 실행 중인 워커 수가 슬롯 상한을 절대 초과하지 않는지 검증."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.task_manager.max_concurrent_vod = 1

    created_workers: list[ControlledWorker] = []

    def _worker_factory(spec: TaskSpec, parent=None) -> ControlledWorker:
        w = ControlledWorker(spec, parent=parent)
        created_workers.append(w)
        return w

    spec1 = TaskSpec(
        task_id="t1", video_url="https://chzzk.naver.com/video/1", save_path="v1.mp4"
    )
    spec2 = TaskSpec(
        task_id="t2", video_url="https://chzzk.naver.com/video/2", save_path="v2.mp4"
    )

    with patch(
        "chzzk_downloader.gui.main_window.VodDownloadWorker",
        side_effect=_worker_factory,
    ):
        window.task_manager.add_task(spec1)
        worker1 = created_workers[0]
        assert worker1.run_started.wait(timeout=2.0)

        # 작업 1 중지 요청 (워커 1은 아직 안 끝남)
        window.task_list_widget.card_stop_requested.emit("t1")

        # 작업 2 시작 시도
        window.task_manager.add_task(spec2)

        # 실행 중인 실제 QThread 워커 수 검증
        running_worker_count = sum(1 for w in created_workers if w.isRunning())
        assert running_worker_count <= window.task_manager.max_concurrent_vod, (
            f"실행 중인 실제 워커 수({running_worker_count})가 슬롯 제한(1)을 초과했습니다."
        )

        # 워커 1 종료 및 슬롯 반환에 따른 작업 2 승계 정리
        worker1.release_finish.set()
        qtbot.waitUntil(lambda: not worker1.isRunning(), timeout=2000)

        if len(created_workers) > 1:
            worker2 = created_workers[1]
            worker2.run_started.wait(timeout=2.0)
            worker2.release_finish.set()
            worker2.cancel()
            qtbot.waitUntil(lambda: not worker2.isRunning(), timeout=2000)

    window.close()


def test_same_task_id_does_not_start_while_previous_worker_alive(app, qtbot):
    """동일한 task_id의 이전 워커가 아직 실행 중일 때 새 워커 구동이 거부되는지 검증."""
    window = MainWindow()
    qtbot.addWidget(window)

    created_workers: list[ControlledWorker] = []

    def _worker_factory(spec: TaskSpec, parent=None) -> ControlledWorker:
        w = ControlledWorker(spec, parent=parent)
        created_workers.append(w)
        return w

    spec = TaskSpec(
        task_id="t1", video_url="https://chzzk.naver.com/video/1", save_path="v1.mp4"
    )

    with patch(
        "chzzk_downloader.gui.main_window.VodDownloadWorker",
        side_effect=_worker_factory,
    ):
        window.task_manager.add_task(spec)
        worker1 = created_workers[0]
        assert worker1.run_started.wait(timeout=2.0)

        # 중지 요청으로 취소 플래그 및 download_stopped 방출 (워커 스레드는 release_finish 대기 중)
        window.task_list_widget.card_stop_requested.emit("t1")
        assert worker1.isRunning()

        # 이전 워커가 아직 실행 중인 상태에서 동일 작업 재다운로드 시도
        window.task_manager.reset_task("t1")
        window.task_manager.add_task(spec)

        # 새 워커가 시작되지 않고 오직 기존 워커 1개만 유지되어야 함 (이전 워커 완료 대기 필요)
        assert len(created_workers) == 1, (
            "이전 워커가 실행 중일 때 동일 task_id에 대한 새 워커가 생성되면 안 됩니다."
        )

        worker1.release_finish.set()
        qtbot.waitUntil(lambda: not worker1.isRunning(), timeout=2000)

        # 이전 워커 정리 완료 후 대기 중이던 신규 워커가 시작되어 DOWNLOADING을 유지해야 함
        qtbot.waitUntil(lambda: len(created_workers) == 2, timeout=2000)
        worker2 = created_workers[1]
        assert window.task_manager.get_task_status("t1") == TaskStatus.DOWNLOADING

        worker2.run_started.wait(timeout=2.0)
        worker2.release_finish.set()
        worker2.cancel()
        qtbot.waitUntil(lambda: not worker2.isRunning(), timeout=2000)

    window.close()


def test_cleanup_removes_only_paths_created_by_worker(tmp_path):
    """워커 취소 시 자신이 기록한 경로만 삭제하고 접두어가 동일한 이웃 파일을 건드리지 않는지 음성 단언 검증."""
    # 1. 파일 준비
    target_path = tmp_path / "[스트리머] 삼국지 (12345).mp4"
    my_part = tmp_path / "[스트리머] 삼국지 (12345).mp4.part"
    my_part.write_text("워커가 작성 중인 파트", encoding="utf-8")

    # 이웃 파일 (동일 접두어)
    sibling_completed = tmp_path / "[스트리머] 삼국지 (12345) (1).mp4"
    sibling_completed.write_text(
        "사용자가 이름 변경으로 저장해 둔 완성본", encoding="utf-8"
    )
    sibling_part = tmp_path / "[스트리머] 삼국지 (12345) (1).mp4.part"
    sibling_part.write_text("다른 작업의 파트 파일", encoding="utf-8")

    spec = TaskSpec(
        task_id="12345",
        video_url="https://chzzk.naver.com/video/12345",
        save_path=str(target_path),
    )
    worker = VodDownloadWorker(spec)

    # 워커가 자신이 만든 경로를 등록한 경우를 흉내
    worker.created_paths.add(my_part)

    # 취소 후 정리 실행 (공개 메서드)
    worker.cleanup_partial_files()

    # 음성 단언 (Negative Assertion): 이웃 파일들은 절대 삭제되어서는 안 됨
    assert sibling_completed.exists(), (
        "접두어가 유사한 이웃 완성 파일이 삭제되지 않고 유지되어야 합니다."
    )
    assert sibling_part.exists(), (
        "접두어가 유사한 이웃 파트 파일이 와일드카드 glob에 의해 오삭제되지 않아야 합니다."
    )


def test_delete_file_keeps_sibling_files(tmp_path):
    """_delete_file_safely가 대상 파일만 삭제하고 접두어가 같은 이웃 파일을 보존하는지 음성 단언 검증."""
    target_file = tmp_path / "삼국지 (12345).mp4"
    target_file.write_text("삭제 대상 완성 파일", encoding="utf-8")
    target_part = tmp_path / "삼국지 (12345).mp4.part"
    target_part.write_text("삭제 대상 임시 파트", encoding="utf-8")

    # 이웃 파일 (동일 접두어 삼국지 (12345))
    sibling_file = tmp_path / "삼국지 (12345) (1).mp4"
    sibling_file.write_text("보존되어야 하는 이웃 파일", encoding="utf-8")
    sibling_part = tmp_path / "삼국지 (12345) (1).mp4.part"
    sibling_part.write_text("보존되어야 하는 이웃 임시 파트", encoding="utf-8")

    # 대상 파일 삭제
    success = _delete_file_safely(target_file)
    assert success is True

    # 대상 파일은 삭제되어야 함
    assert not target_file.exists()

    # 음성 단언 (Negative Assertion): 이웃 파일과 이웃 파트 파일은 온전히 보존되어야 함
    assert sibling_file.exists(), (
        "대상 삭제 시 접두어가 같은 이웃 파일이 와일드카드 glob에 의해 함께 삭제되면 안 됩니다."
    )
    assert sibling_part.exists(), (
        "대상 삭제 시 접두어가 같은 이웃 파트 파일이 함께 삭제되면 안 됩니다."
    )
