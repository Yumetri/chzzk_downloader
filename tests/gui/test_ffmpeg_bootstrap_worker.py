"""FFmpeg 백그라운드 부트스트랩 워커(FFmpegBootstrapWorker) 및 UI 비동기 스레드 보장 GUI 테스트."""

from __future__ import annotations

import io
import subprocess
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QThread, QTimer
from PyQt6.QtWidgets import QApplication

from chzzk_downloader.config import DEFAULT_FFMPEG_BINARY_NAME
from chzzk_downloader.core.ffmpeg_manager import (
    FFmpegProbeResult,
    FFmpegStatus,
    clear_probe_cache,
    ensure_ffmpeg_available,
)
from chzzk_downloader.gui.workers import FFmpegBootstrapWorker


@pytest.mark.ticket("T0110")
def test_ffmpeg_bootstrap_worker_thread(qtbot, tmp_path: Path) -> None:
    """[T0110] FFmpegBootstrapWorker가 백그라운드 스레드에서 블로킹 없이 부트스트랩을 완수하는지 검증."""
    fake_installed = tmp_path / "bin" / DEFAULT_FFMPEG_BINARY_NAME
    fake_installed.parent.mkdir(parents=True, exist_ok=True)
    fake_installed.write_text("fake_ffmpeg", encoding="utf-8")

    worker = FFmpegBootstrapWorker(
        target_dir=str(fake_installed.parent), download_url="http://dummy.url"
    )

    bootstrap_results: list[tuple[bool, str]] = []
    worker.finished_bootstrap.connect(
        lambda ok, path: bootstrap_results.append((ok, path))
    )

    with patch(
        "chzzk_downloader.core.ffmpeg_manager.ensure_ffmpeg_available",
        return_value=(True, fake_installed),
    ):
        with qtbot.waitSignal(worker.finished_bootstrap, timeout=3000):
            worker.start()

    assert len(bootstrap_results) == 1
    assert bootstrap_results[0][0] is True
    assert bootstrap_results[0][1] == str(fake_installed)


@pytest.mark.ticket("T0110")
def test_ffmpeg_synchronous_download_freezes_ui_event_loop(
    qtbot, tmp_path: Path
) -> None:
    """[T0110] [동기 블로킹 검증] 메인 GUI 스레드에서 순수 동기 다운로드 직접 실행 시 UI 이벤트 루프가 완전히 정지(블로킹)됨을 입증."""
    clear_probe_cache()

    # 1. UI 이벤트 루프의 정상 동작을 감시하는 Heartbeat 타이머 등록 (20ms 간격)
    timer_ticks: list[float] = []
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: timer_ticks.append(time.time()))
    timer.start()

    # 2. 원격 네트워크 다운로드 응답 지연 시뮬레이션 (urlopen에서 0.25초 지연)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr(DEFAULT_FFMPEG_BINARY_NAME, b"downloaded_binary_payload")
    zip_data = zip_buffer.getvalue()

    def slow_urlopen(req, *args, **kwargs):
        time.sleep(0.25)
        resp = MagicMock()
        resp.read.return_value = zip_data
        resp.__enter__.return_value = resp
        return resp

    def mock_run(cmd, *args, **kwargs):
        cmd_str = [str(c) for c in cmd]
        if str(tmp_path) in cmd_str[0]:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="ffmpeg version 6.0-essentials_build Copyright\n",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="", stderr="not found"
        )

    with patch("urllib.request.urlopen", side_effect=slow_urlopen):
        with patch("subprocess.run", side_effect=mock_run):
            # 메인 스레드에서 순수 동기 다운로드 실행
            ensure_ffmpeg_available(auto_download=True, target_dir=tmp_path)

    # [검증]: 순수 동기 다운로드는 메인 스레드를 온전히 블로킹하므로 250ms 동안 타이머 틱이 발생하지 않아야 함!
    # (따라서 UI에서는 이를 직접 부르지 않고 반드시 FFmpegBootstrapWorker를 사용해야 함)
    assert len(timer_ticks) == 0, (
        f"순수 동기 다운로드임에도 UI 이벤트가 처리되었습니다. (틱 수: {len(timer_ticks)})"
    )


@pytest.mark.ticket("T0110")
def test_ffmpeg_bootstrap_worker_does_not_block_ui_event_loop(
    qtbot, tmp_path: Path
) -> None:
    """[T0110] [해결 검증] 백그라운드 워커 스레드에서 다운로드 실행 시, 네트워크 응답이 지연되어도 UI 이벤트 루프가 멈추지 않고 반응함을 검증."""
    clear_probe_cache()

    # 1. UI 이벤트 루프 감시 Heartbeat 타이머 등록 (20ms 간격)
    timer_ticks: list[float] = []
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: timer_ticks.append(time.time()))
    timer.start()

    # 2. 동일한 원격 네트워크 지연(urlopen 0.25초) 시뮬레이션
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr(DEFAULT_FFMPEG_BINARY_NAME, b"downloaded_binary_payload")
    zip_data = zip_buffer.getvalue()

    def slow_urlopen(req, *args, **kwargs):
        time.sleep(0.25)
        resp = MagicMock()
        resp.read.return_value = zip_data
        resp.__enter__.return_value = resp
        return resp

    target_bin = tmp_path / DEFAULT_FFMPEG_BINARY_NAME

    def mock_run(cmd, *args, **kwargs):
        cmd_str = [str(c) for c in cmd]
        if str(tmp_path) in cmd_str[0]:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="ffmpeg version 6.0-essentials_build Copyright\n",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="", stderr="not found"
        )

    worker = FFmpegBootstrapWorker(
        target_dir=str(tmp_path), download_url="http://dummy.url"
    )

    with patch("urllib.request.urlopen", side_effect=slow_urlopen):
        with patch("subprocess.run", side_effect=mock_run):
            with qtbot.waitSignal(worker.finished_bootstrap, timeout=3000):
                worker.start()
            assert worker.wait(3000)

    # 3. 워커가 백그라운드에서 다운로드하는 동안에도 메인 UI 스레드는 멈추지 않고 타이머 틱(이벤트)을 지속 처리함
    assert len(timer_ticks) >= 5
    assert target_bin.exists()


@pytest.mark.ticket("T0110")
def test_ui_calls_ffmpeg_download_strictly_in_background_thread(
    qtbot, tmp_path: Path
) -> None:
    """[T0110] [스레드 격리 보장] UI 레벨에서 FFmpeg 다운로드를 수행할 때 메인 GUI 스레드가 아닌 별도 백그라운드 스레드에서만 호출됨을 보장."""
    clear_probe_cache()
    caller_threads: list[QThread] = []
    fake_bin = tmp_path / DEFAULT_FFMPEG_BINARY_NAME

    def spy_download(*args, **kwargs):
        curr = QThread.currentThread()
        assert curr is not None
        caller_threads.append(curr)
        fake_bin.write_text("fake_ffmpeg", encoding="utf-8")
        return fake_bin

    def mock_probe(path=None):
        if path is None or not fake_bin.exists():
            return FFmpegProbeResult(status=FFmpegStatus.NOT_FOUND, path=None)
        return FFmpegProbeResult(
            status=FFmpegStatus.AVAILABLE,
            path=fake_bin,
            version="6.0",
            compatible_args=["-extension_picky", "0"],
        )

    worker = FFmpegBootstrapWorker(target_dir=str(tmp_path))
    results: list[tuple[bool, str]] = []
    worker.finished_bootstrap.connect(lambda ok, msg: results.append((ok, msg)))
    with patch(
        "chzzk_downloader.core.ffmpeg_manager.download_ffmpeg_binary",
        side_effect=spy_download,
    ):
        with patch(
            "chzzk_downloader.core.ffmpeg_manager.probe_ffmpeg", side_effect=mock_probe
        ):
            with qtbot.waitSignal(worker.finished_bootstrap, timeout=2000):
                worker.start()

    assert results != []
    assert results[0][0] is True, f"Worker failed: {results}"
    assert len(caller_threads) == 1
    # [핵심 보장]: 다운로드를 수행한 스레드는 절대 메인 GUI 스레드여서는 안 됨!
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    main_thread = app.thread()
    assert caller_threads[0] != main_thread, (
        "치명적 오류: 다운로드가 메인 GUI 스레드에서 동기로 직접 호출되었습니다!"
    )


@pytest.mark.ticket("T0110")
def test_ui_download_trigger_returns_immediately(qtbot, tmp_path: Path) -> None:
    """[T0110] [논블로킹 보장] UI 레벨에서 다운로드 시작 시 메인 스레드는 0.05초 내로 즉시 반환되어 UI가 멈추지 않아야 함."""
    worker = FFmpegBootstrapWorker(target_dir=str(tmp_path))

    def slow_ensure(*args, **kwargs):
        time.sleep(0.3)
        return True, tmp_path / DEFAULT_FFMPEG_BINARY_NAME

    with patch(
        "chzzk_downloader.core.ffmpeg_manager.ensure_ffmpeg_available",
        side_effect=slow_ensure,
    ):
        start_time = time.time()
        # 워커 시작 호출 (UI 버튼이나 초기화 시 호출되는 액션)
        worker.start()
        elapsed = time.time() - start_time

        # UI 호출 즉시 리턴 검증 (메인 스레드가 50ms 이상 잡히지 않아야 함)
        assert elapsed < 0.05, f"메인 스레드 블로킹 발생! ({elapsed:.3f}초 소요)"

        with qtbot.waitSignal(worker.finished_bootstrap, timeout=2000):
            pass
        assert worker.wait(3000)


@pytest.mark.ticket("T0110")
def test_ffmpeg_bootstrap_worker_cancellation(qtbot, tmp_path: Path) -> None:
    """[T0110] [취소 검증] FFmpegBootstrapWorker 실행 중 cancel() 호출 시 안전하게 중단되고 finished_bootstrap(False)을 방출하는지 검증."""
    worker = FFmpegBootstrapWorker(target_dir=str(tmp_path))
    results: list[tuple[bool, str]] = []
    worker.finished_bootstrap.connect(lambda ok, msg: results.append((ok, msg)))

    def blocking_download(*args, **kwargs):
        cancel_check = kwargs.get("cancel_check")
        for _ in range(10):
            time.sleep(0.05)
            if cancel_check and cancel_check():
                return None
        return None

    with patch(
        "chzzk_downloader.core.ffmpeg_manager.download_ffmpeg_binary",
        side_effect=blocking_download,
    ):
        with patch(
            "chzzk_downloader.core.ffmpeg_manager.probe_ffmpeg",
            return_value=FFmpegProbeResult(status=FFmpegStatus.NOT_FOUND, path=None),
        ):
            with qtbot.waitSignal(worker.finished_bootstrap, timeout=2000):
                worker.start()
                time.sleep(0.05)
                worker.cancel()
            assert worker.wait(3000)

    assert len(results) == 1
    assert results[0][0] is False
    assert "취소" in results[0][1]
