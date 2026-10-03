"""P1 중요 결함 조치 전용 TDD 회귀 검증 테스트 스위트.

검증 항목 (A~L 체크리스트 기반 무맥락 감사):
1. QUEUED 작업 취소 시 카드가 '완료'로 둔갑 및 유령 재생/삭제 버튼 노출 방지 (task_card.py)
2. 파일 잠금(Lock) 등 삭제 실패 시 에러 피드백 및 카드 보존 (task_card.py)
3. TaskInfoWindow.closeEvent C++ 객체 파괴 방어 (task_info_window.py)
4. generate_vod_filename 200자 안전 절단 및 핵심 메타데이터 보존 (filename_generator.py)
5. 프로그레스바 툴팁 호버 깜빡임 방지 및 pct_label 툴팁 동시 연동 (task_card.py)
6. M10 모달 is_danger=True 및 T08 토스트 2.5초 규격 일치 (task_card.py, main_window.py)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PyQt6 import sip
from PyQt6.QtWidgets import QMessageBox

from chzzk_downloader.core.filename_generator import generate_vod_filename
from chzzk_downloader.core.task_models import TaskProgress, TaskStatus
from chzzk_downloader.core.ytdlp import VodInfo
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.task_card import TaskCardWidget
from chzzk_downloader.gui.task_info_window import TaskInfoWindow


@pytest.fixture
def sample_vod_info() -> VodInfo:
    return VodInfo(
        video_no="15033444",
        video_title="치지직 테스트 방송 다시보기",
        channel_name="침착맨",
        duration=3600,
        live_open_date="2026-10-03",
    )


# ---------------------------------------------------------------------------
# 1. QUEUED 작업은 STOPPED로 전이되지 않고 오직 목록 제거만 허용 검증
# ---------------------------------------------------------------------------
def test_queued_task_cannot_trigger_stop_download_only_delete(
    qtbot, sample_vod_info: VodInfo
) -> None:
    """QUEUED(대기열) 상태 작업은 다운로드 중이 아니므로 trigger_stop_download가 거부(False)되어야 하며,
    상태가 STOPPED로 변환되지 않고 오직 목록 삭제(delete_btn / delete_requested)만 가능하다."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15033444",
        status=TaskStatus.QUEUED,
        vod_info=sample_vod_info,
    )
    qtbot.addWidget(card)

    # 1. QUEUED 상태에서는 다운로드 중지(■) 트리거가 무시됨 (False 반환)
    ok = card.trigger_stop_download()
    assert ok is False
    assert card.status == TaskStatus.QUEUED

    card.show()
    card._show_hover_toolbar(True)

    # 2. 호버 시 파일 재생(▶) 및 파일 삭제(🗑️)는 노출되지 않고, 오직 목록에서 제거(✕)만 가능
    assert not card.delete_btn.isHidden()
    assert card.play_btn.isHidden()
    assert card.action_delete_file_btn.isHidden()

    # 3. ✕ 클릭 시 정상적으로 delete_requested 시그널 방출
    delete_spy = MagicMock()
    card.delete_requested.connect(delete_spy)
    card.delete_btn.click()
    delete_spy.assert_called_once()


# ---------------------------------------------------------------------------
# 2. 파일 잠금(Lock) 등 삭제 실패 시 에러 피드백 및 카드 보존
# ---------------------------------------------------------------------------
def test_file_delete_failure_preserves_card_and_shows_error_feedback(
    qtbot, tmp_path: Path, sample_vod_info: VodInfo
) -> None:
    """파일 잠금 또는 권한 오류로 _delete_file_safely가 실패(False)한 경우,
    카드가 삭제되지 않고 목록에 안전하게 보존되어야 하며 사용자에게 에러 피드백이 제공되어야 한다."""
    dummy_file = tmp_path / "locked_video.mp4"
    dummy_file.write_bytes(b"dummy video data")

    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15033444",
        status=TaskStatus.COMPLETED,
        vod_info=sample_vod_info,
    )
    qtbot.addWidget(card)
    card.final_file_path = dummy_file

    delete_signal_spy = MagicMock()
    card.delete_requested.connect(delete_signal_spy)

    # M10 모달은 승인했으나, 파일 안전 삭제는 실패(False)한 상황 시뮬레이션
    with (
        patch("chzzk_downloader.gui.task_card.ask_confirm_dialog", return_value=True),
        patch("chzzk_downloader.gui.task_card._delete_file_safely", return_value=False),
        patch.object(QMessageBox, "warning") as mock_warning,
    ):
        card._on_delete_file_clicked()

        # 삭제 시그널이 방출되지 않고 카드가 보존되어야 함
        delete_signal_spy.assert_not_called()
        # 사용자에게 에러/경고 알림이 주어졌는지 확인
        mock_warning.assert_called_once()


# ---------------------------------------------------------------------------
# 3. TaskInfoWindow.closeEvent C++ 객체 파괴 방어
# ---------------------------------------------------------------------------
def test_task_info_window_close_event_defends_against_deleted_cpp_card(
    qtbot, sample_vod_info: VodInfo
) -> None:
    """TaskCardWidget이 C++ 수준에서 이미 파괴되었거나 is_deleted인 상태에서
    TaskInfoWindow가 닫혀도 RuntimeError 없이 안전하게 종료되어야 한다."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15033444",
        status=TaskStatus.FAILED_DOWNLOAD,
        vod_info=sample_vod_info,
    )
    qtbot.addWidget(card)

    info_win = TaskInfoWindow(card)
    qtbot.addWidget(info_win)

    # 카드를 삭제 상태로 마킹하고 sip 파괴 시뮬레이션
    card.is_deleted = True
    with patch.object(sip, "isdeleted", return_value=True):
        # closeEvent 호출 시 RuntimeError가 발생하지 않아야 함
        try:
            info_win.close()
        except RuntimeError as e:
            pytest.fail(
                f"TaskInfoWindow.closeEvent에서 C++ 파괴 방어가 실패했습니다: {e}"
            )


# ---------------------------------------------------------------------------
# 4. generate_vod_filename 200자 안전 절단 및 핵심 메타데이터 보존
# ---------------------------------------------------------------------------
def test_generate_vod_filename_truncates_title_safely_under_200_chars() -> None:
    """초장문 VOD 제목(300자)이 주어져도 파일명 전체 stem 길이가 200자 이내로 안전 절단되며,
    스트리머, 날짜, 비디오 번호 등 핵심 식별 메타데이터는 온전히 보존되어야 한다."""
    very_long_title = "치지직 " * 80  # 320자 이상의 초장문 제목
    long_vod = VodInfo(
        video_no="15099999",
        video_title=very_long_title,
        channel_name="침착맨플러스",
        live_open_date="2026-10-03",
    )

    filename = generate_vod_filename(long_vod, ext=".mp4")
    p = Path(filename)

    # 1. 확장자 제외 stem 길이가 200자 이하여야 함
    assert len(p.stem) <= 200, (
        f"파일명 stem 길이가 200자를 초과했습니다: len={len(p.stem)}"
    )
    # 2. 필수 접두사 및 접미사가 보존되어야 함
    assert "[침착맨플러스]" in filename
    assert "(15099999)" in filename
    assert "date：2026-10-03" in filename or "date:2026-10-03" in filename
    assert filename.endswith(".mp4")
    # 3. 말줄임표(...)가 포함되어 절단 사실을 명시해야 함
    assert "..." in filename


# ---------------------------------------------------------------------------
# 5. 프로그레스바 툴팁 호버 깜빡임 방지 및 퍼센트 라벨 툴팁 동시 연동
# ---------------------------------------------------------------------------
def test_progress_bar_and_pct_label_tooltip_integration(
    qtbot, sample_vod_info: VodInfo
) -> None:
    """VOD 다운로드 진행 시 프로그레스바(progress_bar)뿐만 아니라
    퍼센트 숫자 라벨(pct_label)에도 툴팁이 동일하게 연동되어야 하며,
    동일 툴팁 재호출 시 불필요한 setToolTip 호출이 방지되어야 한다."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15033444",
        status=TaskStatus.DOWNLOADING,
        vod_info=sample_vod_info,
        is_live=False,
    )
    qtbot.addWidget(card)

    prog = TaskProgress(
        task_id="15033444",
        downloaded_bytes=534_200_000,
        total_bytes=1_250_000_000,
        percentage=42.7,
        speed_str="15.4 MB/s",
        eta_seconds=205,
        eta_str="00:03:25",
        elapsed_seconds=75.0,
    )
    card.update_progress(prog)

    summary = prog.progress_summary
    assert card.progress_bar.toolTip() == summary
    # pct_label에도 툴팁이 연동되어 호버 시 확인 가능해야 함
    assert card.pct_label.toolTip() == summary, (
        "pct_label에도 진행률 요약 툴팁이 연동되어야 합니다."
    )

    # 동일 progress 재전송 시 툴팁 재설정 없이 유지되는지 검증
    with patch.object(card.progress_bar, "setToolTip") as mock_set_tip:
        card.update_progress(prog)
        mock_set_tip.assert_not_called()


# ---------------------------------------------------------------------------
# 6. M10 파일 삭제 모달 is_danger=True 및 T08 토스트 2.5초 규격 일치
# ---------------------------------------------------------------------------
def test_m10_delete_modal_uses_danger_and_t08_uses_2500ms(
    qtbot, tmp_path: Path, sample_vod_info: VodInfo
) -> None:
    """M10 파일 삭제 모달은 is_danger=True(Danger 빨강)로 호출되어야 하며,
    T08 파일 삭제 토스트는 규격서에 명시된 auto_dismiss_ms=2500이어야 한다."""
    dummy_file = tmp_path / "sample.mp4"
    dummy_file.write_bytes(b"test")

    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15033444",
        status=TaskStatus.COMPLETED,
        vod_info=sample_vod_info,
    )
    qtbot.addWidget(card)
    card.final_file_path = dummy_file

    # 1. M10 is_danger=True 전달 검증
    with patch(
        "chzzk_downloader.gui.task_card.ask_confirm_dialog", return_value=False
    ) as mock_dialog:
        card._on_delete_file_clicked()
        mock_dialog.assert_called_once()
        _, kwargs = mock_dialog.call_args
        assert kwargs.get("is_danger") is True, (
            "M10 파일 삭제 모달은 is_danger=True 파라미터를 사용해야 합니다."
        )

    # 2. T08 MainWindow 토스트 2500ms 검증
    main_win = MainWindow()
    qtbot.addWidget(main_win)

    with patch.object(main_win.toast, "show_toast") as mock_toast:
        main_win.show_file_deleted_toast("sample.mp4")
        mock_toast.assert_called_once()
        _, kwargs = mock_toast.call_args
        assert kwargs.get("auto_dismiss_ms") == 2500, (
            "T08 파일 삭제 토스트는 auto_dismiss_ms=2500 (2.5초) 규격이어야 합니다."
        )


# ---------------------------------------------------------------------------
# 7. 결함 #1 검증: live_open_date 내 시:분:초 콜론(:) 전각 정화 및 파일시스템 보호
# ---------------------------------------------------------------------------
def test_generate_vod_filename_with_time_colons_in_live_date() -> None:
    """live_open_date에 시:분:초 콜론이 포함되어 있어도 Windows 금지 문자 ':'가
    전각 콜론(：)으로 안전하게 정화되어야 한다."""
    vod = VodInfo(
        video_no="15033444",
        video_title="치지직 라이브 다시보기",
        channel_name="침착맨",
        live_open_date="2026-10-03 14:30:00",
    )
    filename = generate_vod_filename(vod)

    # Windows 파일시스템에서 파일명 내 ASCII 콜론(:)은 절대 불허됨
    assert ":" not in filename, (
        f"파일명에 Windows 금지 문자 ':'가 포함되어 저장이 실패합니다: {filename}"
    )
    assert "2026-10-03 14：30：00" in filename or "2026-10-03" in filename


# ---------------------------------------------------------------------------
# 8. 결함 #2 검증: 초장문 스트리머명 환경에서도 MAX_STEM_LENGTH 200자 엄격 준수
# ---------------------------------------------------------------------------
def test_generate_vod_filename_with_long_streamer_strictly_under_200_chars() -> None:
    """스트리머 이름 자체가 150자 이상으로 매우 길어도
    최종 파일명 stem 길이는 무조건 200자 이하여야 한다."""
    long_vod = VodInfo(
        video_no="15099999",
        video_title="아주 긴 VOD 제목입니다 " * 20,
        channel_name="매우긴스트리머이름입니다" * 15,  # 접두사 180자 이상
        live_open_date="2026-10-03",
    )
    filename = generate_vod_filename(long_vod, ext=".mp4")
    stem = Path(filename).stem

    assert len(stem) <= 200, f"파일명 stem 길이가 200자를 초과했습니다: len={len(stem)}"
    assert "(15099999)" in filename


# ---------------------------------------------------------------------------
# 9. 결함 #3 검증: DOWNLOADING 상태에서 파일 없이 중단 시 유령 버튼 미노출
# ---------------------------------------------------------------------------
def test_downloading_stopped_without_file_does_not_show_ghost_buttons(
    qtbot, sample_vod_info: VodInfo
) -> None:
    """다운로드 시작 직후 파일이 전혀 생성되지 않은 상태에서 STOPPED된 카드는
    호버 시 재생(▶) 및 파일 삭제(🗑️) 버튼이 노출되지 않아야 한다."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15033444",
        status=TaskStatus.DOWNLOADING,
        vod_info=sample_vod_info,
    )
    qtbot.addWidget(card)
    card.final_file_path = None
    card.target_path = None

    with patch("chzzk_downloader.gui.task_card.ask_confirm_dialog", return_value=True):
        ok = card.trigger_stop_download()
        assert ok is True

    assert card.status == TaskStatus.STOPPED

    card.show()
    card._show_hover_toolbar(True)

    assert card.play_btn.isHidden(), (
        "로컬 파일이 없는 DOWNLOADING 중단 카드에 재생(▶) 버튼이 노출되었습니다."
    )
    assert card.action_delete_file_btn.isHidden(), (
        "로컬 파일이 없는 DOWNLOADING 중단 카드에 파일 삭제(🗑️) 버튼이 노출되었습니다."
    )
    assert not card.delete_btn.isHidden()


# ---------------------------------------------------------------------------
# 10. 결함 #4 검증: TaskInfoWindow.refresh_info C++ 객체 파괴 방어
# ---------------------------------------------------------------------------
def test_task_info_window_refresh_info_defends_against_deleted_cpp_card(
    qtbot, sample_vod_info: VodInfo
) -> None:
    """TaskCardWidget이 파괴된 상태에서 refresh_info()가 호출되어도
    RuntimeError 없이 안전하게 방어되어야 한다."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15033444",
        status=TaskStatus.READY,
        vod_info=sample_vod_info,
    )
    qtbot.addWidget(card)
    info_win = TaskInfoWindow(card)
    qtbot.addWidget(info_win)

    card.is_deleted = True
    with patch.object(sip, "isdeleted", return_value=True):
        try:
            info_win.refresh_info()
        except RuntimeError as e:
            pytest.fail(f"refresh_info에서 파괴된 C++ 객체 접근으로 크래시 발생: {e}")


# ---------------------------------------------------------------------------
# 11. 결함 #5 검증: 이미 외부에서 삭제된 파일에 대해 쓰레기통 클릭 시 카드 정상 정리
# ---------------------------------------------------------------------------
def test_delete_non_existent_file_removes_card_without_busy_lock_error(
    qtbot, sample_vod_info: VodInfo, tmp_path: Path
) -> None:
    """디스크에서 이미 파일이 삭제된 경우, '다른 프로그램에서 사용 중'이라는
    엉뚱한 잠금 에러를 띄우지 않고 카드가 목록에서 정상 정리되어야 한다."""
    missing_file = tmp_path / "already_deleted.mp4"
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15033444",
        status=TaskStatus.COMPLETED,
        vod_info=sample_vod_info,
    )
    qtbot.addWidget(card)
    card.final_file_path = missing_file

    delete_signal_spy = MagicMock()
    card.delete_requested.connect(delete_signal_spy)

    with (
        patch("chzzk_downloader.gui.task_card.ask_confirm_dialog", return_value=True),
        patch.object(QMessageBox, "warning") as mock_warning,
    ):
        card._on_delete_file_clicked()

        # 이미 없는 파일에 대해 '사용 중' 경고 팝업이 뜨지 않아야 함
        mock_warning.assert_not_called()
        # 카드는 목록에서 깔끔하게 제거되어야 함
        delete_signal_spy.assert_called_once()
