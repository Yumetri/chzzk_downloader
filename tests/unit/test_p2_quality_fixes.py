"""P2 품질 개선 및 결함 방어 회귀 테스트 스위트 (TDD 선행 재현).

검증 대상:
1. TaskManager.cancel_task의 READY 상태 안전 취소 및 STOPPED 전이
2. SpinnerWidget.hideEvent 트리거 시 회전 타이머 자동 중단 (CPU 누수 방어)
3. 토스트 알림(완료, 파일 삭제 등) 내 파일명/URL의 HTML 이스케이프 보강 (XSS 및 서식 깨짐 차단)
"""

import html
from pathlib import Path

from chzzk_downloader.core.task_manager import TaskManager
from chzzk_downloader.core.task_models import TaskSpec, TaskStatus
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.task_card import SpinnerWidget, TaskCardWidget


# ---------------------------------------------------------------------------
# 1. READY 상태 작업은 cancel_task가 아닌 remove_task로 처리 검증
# ---------------------------------------------------------------------------
def test_ready_task_cannot_cancel_only_remove() -> None:
    """READY(준비) 상태 작업은 다운로드 중이 아니므로 cancel_task가 거부(False)되어야 하며,
    작업 정리는 remove_task를 통해 수행되어야 한다."""
    manager = TaskManager(max_concurrent_vod=2)
    spec = TaskSpec(
        task_id="vod_ready_test_1",
        video_url="https://chzzk.naver.com/video/10001",
        save_path=Path("/tmp/ready_test.mp4"),
    )

    manager.add_task(spec)
    manager.reset_task(spec.task_id)
    assert manager.get_task_status(spec.task_id) == TaskStatus.READY

    # 1. READY 상태에서 cancel_task는 거부(False)됨 (DOWNLOADING 상태만 STOPPED 전이 가능)
    ok = manager.cancel_task(spec.task_id)
    assert ok is False
    assert manager.get_task_status(spec.task_id) == TaskStatus.READY

    # 2. 작업 정리는 remove_task를 통해 안전하게 삭제됨
    removed = manager.remove_task(spec.task_id)
    assert removed is True
    assert manager.get_task_status(spec.task_id) is None


# ---------------------------------------------------------------------------
# 2. SpinnerWidget.hideEvent 트리거 시 타이머 자동 중단 테스트
# ---------------------------------------------------------------------------
def test_spinner_widget_hide_event_stops_timer(qtbot) -> None:
    """SpinnerWidget이 숨겨질 때(hideEvent), 내부 회전 QTimer가
    자동으로 stop()되어 백그라운드 CPU 낭비 및 재렌더링을 차단해야 한다."""
    spinner = SpinnerWidget(size=16)
    qtbot.addWidget(spinner)
    spinner.show()

    # 스피너 회전 시작
    spinner.start()
    assert spinner._timer.isActive() is True, "start() 후 타이머가 활성화되어야 합니다."

    # 스피너 위젯 숨김 (hideEvent 트리거)
    spinner.hide()

    # hideEvent에 의해 타이머가 멈추었는지 검증
    assert spinner._timer.isActive() is False, (
        "hideEvent 트리거 시 내부 회전 타이머가 비활성화(stop)되어야 합니다."
    )
    assert spinner._angle == 0, "hideEvent 시 각도가 0으로 초기화되어야 합니다."


# ---------------------------------------------------------------------------
# 3. 토스트 알림 HTML 이스케이프 보강 테스트
# ---------------------------------------------------------------------------
def test_toast_html_escape_for_special_characters(qtbot, tmp_path: Path) -> None:
    """VOD 제목이나 파일명에 '<script>', '<test>', '&' 등 HTML 특수문자가 포함된 경우,
    토스트에 전달되는 HTML 메시지에서 이스케이프 처리(html.escape)되어
    XSS 및 서식 깨짐이 방지되어야 한다."""
    # MainWindow 생성 및 초기화
    win = MainWindow()
    qtbot.addWidget(win)

    dangerous_name = "<evil_tag> & 'test' \"vod\".mp4"

    # 1. show_file_deleted_toast 검증
    win.show_file_deleted_toast(dangerous_name)
    toast_text = win.toast.label.text()

    # raw '<evil_tag>'가 본문에 노출되지 않고 '&lt;evil_tag&gt;'로 이스케이프되어야 함
    assert "<evil_tag>" not in toast_text, "위험한 태그가 원문 그대로 노출되었습니다."
    assert html.escape(dangerous_name) in toast_text, (
        "파일명이 html.escape 처리되어 포함되어야 합니다."
    )

    # 2. _on_task_completed 검증
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/99999",
        status=TaskStatus.DOWNLOADING,
    )
    card.task_id = "test_task_esc"
    win.task_list_widget.add_task_card(card)

    fake_completed_path = str(tmp_path / dangerous_name)
    win._on_task_completed("test_task_esc", fake_completed_path)

    completed_toast_text = win.toast.label.text()
    assert "<evil_tag>" not in completed_toast_text, (
        "완료 토스트에 위험한 태그가 원문 그대로 노출되었습니다."
    )
    assert html.escape(dangerous_name) in completed_toast_text, (
        "완료 토스트 파일명이 html.escape 처리되어야 합니다."
    )


# ---------------------------------------------------------------------------
# 4. 결함 #1 검증: SpinnerWidget 숨김 후 복원 시 회전 재개 (대칭적 라이프사이클)
# ---------------------------------------------------------------------------
def test_spinner_widget_show_restores_running_timer(qtbot) -> None:
    """SpinnerWidget이 동작 중 숨겨졌다가(hide) 다시 노출될 때(show),
    영구 정지(Freeze)되지 않고 회전 타이머가 대칭적으로 안전하게 재개되어야 한다."""
    spinner = SpinnerWidget(size=16)
    qtbot.addWidget(spinner)
    spinner.show()

    # 1. 회전 시작
    spinner.start()
    assert spinner._timer.isActive() is True

    # 2. 일시 숨김 -> 타이머 일시 중지
    spinner.hide()
    assert spinner._timer.isActive() is False

    # 3. 창 복원/재표시 -> 타이머 자동 재개 검증
    spinner.show()
    assert spinner._timer.isActive() is True, (
        "동작 중 숨겨졌던 스피너는 show 시 타이머가 재개되어야 합니다."
    )

    # 4. 사용자가 명시적으로 stop()한 경우: show되어도 재개되지 않아야 함
    spinner.stop()
    assert spinner._timer.isActive() is False
    spinner.hide()
    spinner.show()
    assert spinner._timer.isActive() is False, (
        "명시적으로 stop()된 스피너는 show 시 자동으로 회전하면 안 됩니다."
    )


# ---------------------------------------------------------------------------
# 5. 결함 #2 검증: MainWindow URL 입력 및 다운로드 차단 토스트 HTML 이스케이프
# ---------------------------------------------------------------------------
def test_mainwindow_download_clicked_and_blocked_toast_html_escape(qtbot) -> None:
    """_on_download_clicked 및 _on_download_blocked에서 생성되는 토스트 메시지에
    특수문자가 포함된 경우 html.escape가 적용되어 원문 태그가 노출되지 않아야 한다."""
    win = MainWindow()
    qtbot.addWidget(win)

    # 1. URL 입력 및 다운로드 클릭 토스트
    dangerous_url = "https://chzzk.naver.com/video/10001?q=<script>&ref=1"
    win.url_input.setText(dangerous_url)
    win._on_download_clicked()

    url_toast_text = win.toast.label.text()
    assert "<script>" not in url_toast_text, "URL 내 HTML 태그가 escape되지 않았습니다."
    assert html.escape(dangerous_url) in url_toast_text

    # 2. 다운로드 차단 토스트
    dangerous_reason = "FFmpeg 오류: <stream_error> & codec failure"
    win._on_download_blocked(dangerous_reason)

    blocked_toast_text = win.toast.label.text()
    assert "<stream_error>" not in blocked_toast_text, (
        "차단 사유 내 HTML 태그가 escape되지 않았습니다."
    )
    assert html.escape(dangerous_reason) in blocked_toast_text
