"""이슈 #19 최종 적대적 검증 결함(Round 5) 검증 단위 테스트."""

import time
from unittest.mock import patch

import pytest
from PyQt6 import sip
from PyQt6.QtWidgets import QApplication

from chzzk_downloader.core.filename_generator import sanitize_filename
from chzzk_downloader.core.task_manager import TaskManager
from chzzk_downloader.core.task_models import TaskProgress, TaskSpec, TaskStatus
from chzzk_downloader.core.ytdlp import VodFormatInfo, VodInfo
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.task_card import TaskCardWidget
from chzzk_downloader.gui.workers import VodDownloadWorker, build_vod_download_opts


@pytest.fixture
def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    return instance


def test_defect1_zombie_download_after_cancellation_race(app, tmp_path):
    """[결함 1 검증] 슬롯 승계 지연 시그널 도착 전 사용자가 취소했을 때 좀비 다운로드가 부활하지 않아야 함."""
    window = MainWindow()
    window.task_manager.max_concurrent_vod = 1

    info1 = VodInfo(
        "t1", "Title 1", "Streamer", "", 100, [VodFormatInfo("1080p", "1080p", 60)]
    )
    info2 = VodInfo(
        "t2", "Title 2", "Streamer", "", 100, [VodFormatInfo("1080p", "1080p", 60)]
    )
    card1 = TaskCardWidget(
        "https://chzzk.naver.com/video/t1",
        status=TaskStatus.READY,
        vod_info=info1,
        parent=window,
    )
    card2 = TaskCardWidget(
        "https://chzzk.naver.com/video/t2",
        status=TaskStatus.READY,
        vod_info=info2,
        parent=window,
    )
    window.task_list_widget.add_task_card(card1)
    window.task_list_widget.add_task_card(card2)

    with (
        patch(
            "chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available",
            return_value=True,
        ),
        patch("chzzk_downloader.gui.workers.VodDownloadWorker.start"),
    ):
        card1.trigger_start_download()
        card2.trigger_start_download()

    assert card1.status == TaskStatus.DOWNLOADING
    assert card2.status == TaskStatus.QUEUED

    # 1. t1 완료로 t2가 DOWNLOADING 전이되었으나 지연 시그널이 큐에 남아있는 상황 모사
    window.task_manager.signals.blockSignals(True)
    window.task_manager.report_completed("t1", str(tmp_path / "t1.mp4"))
    window.task_manager.signals.blockSignals(False)
    # 2. 사용자가 지연 시그널 도착 전 t2 취소
    window.task_manager.cancel_task("t2")
    assert window.task_manager.get_task_status("t2") == TaskStatus.STOPPED

    # 3. 뒤늦게 이전 상태 전이 시그널 도착
    window._on_task_status_changed("t2", TaskStatus.QUEUED, TaskStatus.DOWNLOADING)

    # 결함 증명: card2가 DOWNLOADING으로 부활하지 않고 STOPPED를 유지해야 하며, 워커가 시작되지 않아야 함
    assert card2.status == TaskStatus.STOPPED, (
        f"Task revived to {card2.status} instead of STOPPED"
    )
    assert "t2" not in window._download_workers, (
        "Zombie worker was spawned for STOPPED task!"
    )
    window.close()


def test_defect2_cleanup_worker_logic_inversion(app, tmp_path):
    """[결함 2 검증] 워커 정상 종료 시 _download_workers에서 pop되고, 이전 워커 정리가 신규 워커를 증발시키지 않아야 함."""
    window = MainWindow()
    spec = TaskSpec(
        "task_x", "https://chzzk.naver.com/video/task_x", save_path=tmp_path / "x.mp4"
    )

    # 1. 정상 종료 시: 워커가 _download_workers에서 pop되어야 함
    worker1 = VodDownloadWorker(spec, parent=window)
    window._download_workers["task_x"] = worker1
    window._cleanup_worker("task_x", worker1)
    assert "task_x" not in window._download_workers, (
        f"종료된 워커가 pop되지 않고 딕셔너리에 잔존: {window._download_workers.get('task_x')}"
    )

    # 2. 재다운로드 중 이전 워커 정리 시: 신규 워커가 보존되어야 함
    worker_new = VodDownloadWorker(spec, parent=window)
    window._download_workers["task_x"] = worker_new
    window._cleanup_worker("task_x", worker1)  # old worker 정리 호출
    assert window._download_workers.get("task_x") is worker_new, (
        "이전 워커 정리 호출이 신규 워커를 증발시킴!"
    )
    window.close()


def test_defect3_task_info_window_dangling_reference(app):
    """[결함 3 검증] 작업 카드 삭제 시 열려 있는 TaskInfoWindow도 함께 닫혀 댕글링 크래시가 없어야 함."""
    window = MainWindow()
    card = TaskCardWidget(
        "https://chzzk.naver.com/video/999", status=TaskStatus.READY, parent=window
    )
    window.task_list_widget.add_task_card(card)

    card.open_task_info_window()
    info_win = card._info_win
    assert info_win is not None and info_win.isVisible()

    # 카드를 UI 목록에서 단독 삭제
    window.task_list_widget.remove_task_card(card)
    app.processEvents()

    # 결함 증명: 카드가 삭제되었을 때 종속된 정보창도 닫히거나 파기되어야 함
    assert sip.isdeleted(info_win) or not info_win.isVisible(), (
        "카드가 삭제되었음에도 종속된 TaskInfoWindow가 닫히지 않고 화면에 남아있음"
    )
    window.close()


def test_defect4_unescaped_percent_in_outtmpl(tmp_path):
    """[결함 4 검증] 비디오 제목에 '%' 포함 시 outtmpl에서 '%%'로 이스케이프되어 yt-dlp 서식 파싱 에러를 방지해야 함."""
    title = "승률 100% 도전"
    sanitized = sanitize_filename(f"[스트리머] {title} (12345)")
    spec = TaskSpec(
        "12345",
        "https://chzzk.naver.com/video/12345",
        title=title,
        save_path=tmp_path / f"{sanitized}.mp4",
    )

    opts = build_vod_download_opts(spec)
    outtmpl_str = opts["outtmpl"]["default"]

    assert "100%%" in outtmpl_str, (
        f"outtmpl에 이스케이프되지 않은 '%'가 포함되어 yt-dlp 파싱 실패 위험: {outtmpl_str}"
    )


def test_defect5_progress_over_100_bypasses_throttle():
    """[결함 5 검증] 100% 초과 진행률(105% 등) 유입 시에도 100ms 스로틀링이 우회되지 않고 정상 제한되어야 함."""
    tm = TaskManager(max_concurrent_vod=1, progress_throttle_interval_sec=0.1)
    tm.add_task(TaskSpec("hls_1", "https://url"))

    emitted_count = 0
    tm.signals.task_progress_updated.connect(lambda *args: inc())

    def inc():
        nonlocal emitted_count
        emitted_count += 1

    # 105% 진행률로 5ms 간격 10회 연속 보고
    for _ in range(10):
        tm.report_progress("hls_1", TaskProgress("hls_1", percentage=105.0))
        time.sleep(0.005)

    assert emitted_count < 5, (
        f"100% 초과 진행률로 인해 스로틀링이 우회되어 10회 중 {emitted_count}회가 즉시 방출됨"
    )


def test_defect6_best_quality_korean_string_filter(tmp_path):
    """[결함 6 검증] '최고 화질' 선택 시 format 옵션에 '최고 화질' 리터럴이 들어가지 않고 표준 포맷이어야 함."""
    spec = TaskSpec(
        "q_1",
        "https://chzzk.naver.com/video/q_1",
        selected_quality="최고 화질",
        save_path=tmp_path / "q1.mp4",
    )
    opts = build_vod_download_opts(spec)
    format_opt = opts.get("format", "")
    assert "최고 화질" not in format_opt, (
        f"format 옵션에 한글 '최고 화질'이 주입됨: {format_opt}"
    )
