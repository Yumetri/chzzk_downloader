"""T0112. 다운로드 진행률과 완료 상태 단위 및 GUI 테스트.

- TaskProgress 데이터 모델 경과 시간 및 포맷팅 프로퍼티 검증
- VodDownloadWorker 경과 시간 주입 및 0바이트 파일 방어 검증
- TaskCardWidget 3번 위치 미니멀 QProgressBar, 정수%, 우측 3대 메트릭(속도/시간/용량) 렌더링 검증
- TaskCardWidget 완료(COMPLETED) 시 영상 시간 및 최종 디스크 용량 표시 검증
- TaskCardWidget 2번 위치 [🗑️ 파일 삭제] 활성화(DOWNLOADING, STOPPED, COMPLETED) 및 M11 모달 연동 검증
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QApplication

from chzzk_downloader.core.task_models import TaskProgress, TaskSpec, TaskStatus
from chzzk_downloader.core.ytdlp import VodInfo
from chzzk_downloader.gui.task_card import TaskCardWidget
from chzzk_downloader.gui.workers import VodDownloadWorker


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


# ============================================================================
# 1. TaskProgress 데이터 모델 확장 검증
# ============================================================================


def test_task_progress_elapsed_and_formatting_properties():
    """TaskProgress에 추가된 경과 시간 및 단위 변환 편의 프로퍼티가 정상 동작하는지 검증."""
    progress = TaskProgress(
        task_id="test_task_1",
        downloaded_bytes=144_492_134,  # ~137.8 MB
        total_bytes=1_288_490_188,  # ~1.20 GB
        percentage=11.214,
        speed_bytes_sec=765_440.0,
        speed_str="747.5 KB/s",
        eta_seconds=1495,
        eta_str="00:24:55",
        elapsed_seconds=160.0,  # 2분 40초
    )

    # 1. 경과 시간 포맷팅
    assert progress.elapsed_seconds == 160.0
    assert progress.elapsed_str == "00:02:40"

    # 2. 바이트 포맷팅 프로퍼티
    assert "137.8 MB" in progress.downloaded_size_str
    assert "1.20 GB" in progress.total_size_str

    # 3. 소수점 정밀 퍼센트 및 종합 서머리
    assert progress.detailed_percentage_str == "11.2%"
    assert "11.2%" in progress.progress_summary
    assert "137.8 MB" in progress.progress_summary
    assert "1.20 GB" in progress.progress_summary


def test_task_progress_unknown_total_bytes_handling():
    """total_bytes가 0이거나 알 수 없을 때도 에러 없이 유연하게 처리되는지 검증."""
    progress = TaskProgress(
        task_id="test_task_2",
        downloaded_bytes=52_428_800,  # 50.0 MB
        total_bytes=0,
        percentage=0.0,
        elapsed_seconds=45.0,
    )

    assert progress.elapsed_str == "00:00:45"
    assert "50.0 MB" in progress.downloaded_size_str
    assert progress.total_size_str in ("--", "알 수 없음", "")
    assert "50.0 MB" in progress.progress_summary


# ============================================================================
# 2. VodDownloadWorker 검증 (경과 시간 및 0바이트 빈 파일 방어)
# ============================================================================


def test_worker_progress_hook_injects_elapsed_seconds():
    """_progress_hook에서 시작 시점 기준 elapsed_seconds를 올바르게 계산하여 emit하는지 검증."""
    spec = TaskSpec(
        task_id="task_worker_1",
        video_url="https://chzzk.naver.com/video/12345",
        save_path=Path("/tmp/test.mp4"),
    )
    worker = VodDownloadWorker(spec)
    worker._start_time = 1000.0  # mock start time

    emitted_progress = []
    worker.progress_updated.connect(emitted_progress.append)

    with patch("time.perf_counter", return_value=1015.5):  # 15.5초 경과
        with patch("time.monotonic", return_value=10.0):
            d = {
                "status": "downloading",
                "downloaded_bytes": 1024 * 1024 * 10,
                "total_bytes": 1024 * 1024 * 100,
                "speed": 1024 * 1024 * 2,
                "eta": 45,
            }
            worker._progress_hook(d)

    assert len(emitted_progress) == 1
    prog = emitted_progress[0]
    assert prog.elapsed_seconds == pytest.approx(15.5, rel=1e-2)
    assert prog.elapsed_str == "00:00:15"


def test_worker_run_detects_empty_zero_byte_file(tmp_path):
    """다운로드 완료 시점에 파일이 0바이트이면 FileNotFoundError/ValueError 예외를 발생시키는지 검증."""
    zero_file = tmp_path / "empty_video.mp4"
    zero_file.write_bytes(b"")  # 0바이트 파일

    spec = TaskSpec(
        task_id="task_zero_byte",
        video_url="https://chzzk.naver.com/video/99999",
        save_path=zero_file,
    )
    worker = VodDownloadWorker(spec)

    failed_signals = []
    worker.download_failed.connect(lambda *args: failed_signals.append(args))

    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        mock_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_instance
        # ydl.download는 에러 없이 종료되었다고 가정
        mock_instance.download.return_value = 0

        worker.run()

    # 0바이트 파일이므로 완료가 아닌 실패로 전이되어야 함
    assert len(failed_signals) == 1
    task_id, err_type, msg, _tb = failed_signals[0]
    assert task_id == "task_zero_byte"
    assert "0" in msg or "크기" in msg or "빈" in msg or "생성되지 않았습니다" in msg


# ============================================================================
# 3. TaskCardWidget 3번 위치 UI 렌더링 검증
# ============================================================================


def test_task_card_downloading_ui_elements_and_progress_update(qapp):
    """DOWNLOADING 상태에서 3번 위치 프로그레스바, 정수% 라벨, 우측 3대 메트릭이 정상 표시되는지 검증."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15460500",
        status=TaskStatus.READY,
        video_no="15460500",
    )
    card.status = TaskStatus.DOWNLOADING
    card._update_display()

    # 3번 위치 UI 위젯 존재 확인
    assert hasattr(card, "progress_bar")
    assert hasattr(card, "pct_label")
    assert hasattr(card, "speed_label")
    assert hasattr(card, "elapsed_label")
    assert hasattr(card, "size_label")

    # DOWNLOADING 상태에서 3번 위치 메트릭 위젯 표시 확인
    assert not card.progress_bar.isHidden()
    assert not card.pct_label.isHidden()
    assert not card.speed_label.isHidden()
    assert not card.elapsed_label.isHidden()
    assert not card.size_label.isHidden()

    # 진행 상태 갱신
    progress = TaskProgress(
        task_id="15460500",
        downloaded_bytes=144_492_134,  # ~137.8 MB
        total_bytes=1_288_490_188,  # ~1.20 GB
        percentage=11.2,
        speed_bytes_sec=765_440.0,
        speed_str="747.5 KB/s",
        eta_seconds=1495,
        eta_str="00:24:55",
        elapsed_seconds=160.0,
    )
    card.update_progress(progress)

    # 렌더링 검증
    assert card.progress_bar.value() == 11
    assert "11%" in card.pct_label.text()
    assert "747.5 KB/s" in card.speed_label.text()
    assert "00:02:40" in card.elapsed_label.text()
    assert "137.8 MB" in card.size_label.text()


def test_task_card_completed_ui_shows_duration_and_final_size(qapp, tmp_path):
    """COMPLETED 상태 시 진행바는 숨겨지고 3번 위치에 [영상 시간 | 최종 용량]이 표시되는지 검증."""
    final_file = tmp_path / "complete_video.mp4"
    final_file.write_bytes(b"A" * (1024 * 1024 * 25))  # 25 MB

    info = VodInfo(
        video_no="15460500",
        video_title="테스트 방송",
        channel_name="스트리머",
        duration=3665,  # 01:01:05
    )
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15460500",
        status=TaskStatus.READY,
        vod_info=info,
    )
    card.set_completed(final_file)

    # 진행바는 숨김 처리
    assert card.progress_bar.isHidden()

    # 3번 위치 라벨에 재생시간과 최종용량이 포함되어야 함
    text = card.status_label.text()
    assert "01:01:05" in text
    assert "25.0 MB" in text or "25 MB" in text


# ============================================================================
# 4. TaskCardWidget 파일 삭제 [🗑️] 액션 및 M11 모달 검증
# ============================================================================


def test_delete_file_action_enabled_states(qapp):
    """파일 삭제 [🗑️] 버튼이 DOWNLOADING, STOPPED, COMPLETED 상태에서 호버 시 활성화되는지 검증."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15460500",
        status=TaskStatus.READY,
    )
    assert hasattr(card, "action_delete_file_btn")

    # READY, QUEUED 등 파일이 없는 초기 상태에서는 호버해도 파일 삭제 버튼은 숨김
    card.set_task_status(TaskStatus.READY)
    card._show_hover_toolbar(True)
    assert card.action_delete_file_btn.isHidden()

    # DOWNLOADING 상태에서 호버 시 활성화
    card.set_task_status(TaskStatus.DOWNLOADING)
    card._show_hover_toolbar(True)
    assert not card.action_delete_file_btn.isHidden()

    # STOPPED 상태에서 호버 시 활성화
    card.set_task_status(TaskStatus.STOPPED)
    card._show_hover_toolbar(True)
    assert not card.action_delete_file_btn.isHidden()

    # COMPLETED 상태에서 호버 시 활성화
    card.set_task_status(TaskStatus.COMPLETED)
    card._show_hover_toolbar(True)
    assert not card.action_delete_file_btn.isHidden()

    # 호버 해제 시 전체 툴바 숨김
    card._show_hover_toolbar(False)
    assert card.action_delete_file_btn.isHidden()


def test_task_card_stopped_shows_actual_downloaded_duration_not_total_vod(
    qtbot,
):
    """다운로드 도중 중단 시 3번 위치에 전체 영상 길이가 아닌 실제 다운로드된 영상 길이가 표시되는지 검증."""
    vod_info = VodInfo(
        video_no="15033444",
        video_title="테스트 영상",
        channel_name="테스트 스트리머",
        duration=3600,
    )
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15033444",
        status=TaskStatus.DOWNLOADING,
        vod_info=vod_info,
        is_live=False,
    )
    qtbot.addWidget(card)

    # 25% 다운로드 진행 (3600초의 25% = 900초 = 15분)
    prog = TaskProgress(
        task_id="15033444",
        downloaded_bytes=250_000_000,
        total_bytes=1_000_000_000,
        percentage=25.0,
        speed_str="10.0 MB/s",
        eta_seconds=2700,
        eta_str="00:45:00",
        elapsed_seconds=300.0,
    )
    card.update_progress(prog)

    # 중단 상태로 전이
    card.set_task_status(TaskStatus.STOPPED)

    # 전체 길이(01:00:00)가 아니라 실제 다운로드 분량(15:00)이 노출되어야 함
    assert card.time_metric_label.text() == "15:00", (
        f"중단 시 실제 다운로드된 영상 길이가 아닌 다른 값이 표시되었습니다: {card.time_metric_label.text()}"
    )


def test_delete_file_action_triggers_m11_and_deletes_file(qapp, tmp_path):
    """파일 삭제 클릭 시 M11 모달 승인을 거쳐 파일이 삭제되고 카드가 자동 제거 요청되는지 검증."""
    dummy_file = tmp_path / "to_delete.mp4"
    dummy_file.write_bytes(b"dummy video content")

    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15460500",
        status=TaskStatus.READY,
    )
    card.set_completed(dummy_file)

    delete_signals = []
    card.delete_requested.connect(lambda: delete_signals.append(True))

    with patch(
        "chzzk_downloader.gui.task_card.ask_confirm_dialog", return_value=True
    ) as mock_dialog:
        card._on_delete_file_clicked()

        mock_dialog.assert_called_once()
        # M11 확인 모달 문구에 파일명이 포함되어야 함
        args, kwargs = mock_dialog.call_args
        modal_text = kwargs.get("text", args[1] if len(args) > 1 else "")
        assert "다음 파일이 삭제됩니다" in modal_text
        assert "to_delete.mp4" in modal_text

    # 파일이 삭제되었거나 휴지통으로 이동되어야 함
    assert not dummy_file.exists()
    # 작업 목록에서 카드를 자동 제거하기 위한 시그널 방출 확인
    assert len(delete_signals) == 1


def test_delete_file_action_while_downloading_cleans_part_files_and_emits_stop(
    qapp, tmp_path
):
    """다운로드 중(DOWNLOADING) 파일 삭제 클릭 시 프로세스 중단 요청 및 임시 파일(.part)까지 청소하는지 검증."""
    target_mp4 = tmp_path / "stream_video.mp4"
    part_file = tmp_path / "stream_video.mp4.part"
    part_file.write_bytes(b"downloading chunk data...")

    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15460500",
        status=TaskStatus.DOWNLOADING,
    )
    card.target_path = target_mp4

    stop_signals = []
    delete_signals = []
    card.request_stop_download.connect(stop_signals.append)
    card.delete_requested.connect(lambda: delete_signals.append(True))

    with patch("chzzk_downloader.gui.task_card.ask_confirm_dialog", return_value=True):
        card._on_delete_file_clicked()

    # 1. 다운로드 중지 시그널 방출 확인
    assert len(stop_signals) == 1
    assert stop_signals[0] == card.task_id

    # 2. 임시 파일(.part)도 함께 삭제되어야 함
    assert not part_file.exists()

    # 3. 작업 목록 카드 제거 시그널 방출 확인
    assert len(delete_signals) == 1


# ============================================================================
# 5. 적대적 검증 피드백 보강 테스트 (NaN 방어, 0바이트 파일 정리, ctypes 패킹)
# ============================================================================


def test_task_card_update_progress_nan_handling(qapp):
    """progress.percentage가 NaN 또는 Inf일 때 UI 크래시 없이 0%로 안전하게 폴백되는지 검증."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15460500",
        status=TaskStatus.DOWNLOADING,
    )
    card._update_display()

    nan_progress = TaskProgress(
        task_id="15460500",
        percentage=float("nan"),
    )
    # 크래시 없이 정상 실행되어야 함
    card.update_progress(nan_progress)
    assert card.progress_bar.value() == 0
    assert card.pct_label.text() == "0%"
    assert nan_progress.detailed_percentage_str == "0.0%"


def test_worker_run_cleans_up_zero_byte_file(tmp_path):
    """0바이트 파일 감지 시 실패로 전이됨과 동시에 0바이트 빈 파일이 디스크에서 안전하게 제거되는지 검증."""
    zero_file = tmp_path / "empty_video.mp4"
    zero_file.write_bytes(b"")

    spec = TaskSpec(
        task_id="task_zero_clean",
        video_url="https://chzzk.naver.com/video/99999",
        save_path=zero_file,
    )
    worker = VodDownloadWorker(spec)

    with patch("yt_dlp.YoutubeDL") as mock_ydl:
        mock_instance = MagicMock()
        mock_ydl.return_value.__enter__.return_value = mock_instance
        mock_instance.download.return_value = 0

        worker.run()

    # 0바이트 빈 파일이 디스크에 방치되지 않고 정리되어야 함
    assert not zero_file.exists()


def test_trigger_start_download_delegates_to_manager_when_connected(qapp):
    """상위 관제탑(MainWindow)의 request_start_download 리시버가 연결되어 있으면 독단적으로 DOWNLOADING으로 전이하지 않는지 검증."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15460500",
        status=TaskStatus.READY,
        vod_info=VodInfo(
            video_no="15460500", video_title="테스트", channel_name="스트리머"
        ),
    )

    received_specs = []
    card.request_start_download.connect(received_specs.append)

    with patch(
        "chzzk_downloader.core.ffmpeg_manager.is_ffmpeg_available",
        return_value=True,
    ):
        ok = card.trigger_start_download()

    assert ok is True
    assert len(received_specs) == 1
    # 상위 관제탑의 응답을 기다려야 하므로 독단적으로 DOWNLOADING이 되지 않고 READY를 유지
    assert card.status == TaskStatus.READY


def test_shfileopstructw_packing_alignment():
    """Windows ctypes SHFILEOPSTRUCTW 구조체가 x64 표준 정렬(56바이트)을 정확히 만족하는지 검증."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.WORD),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    # Windows 64비트 CPython 환경에서 기본 정렬 시 x64 Windows SDK와 일치하는 56바이트여야 함
    if sys.platform == "win32" and sys.maxsize > 2**32:
        assert ctypes.sizeof(SHFILEOPSTRUCTW) == 56
