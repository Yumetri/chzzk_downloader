"""T0106. 쿠키 파일·문자열 등록, Modeless 설정창, 4대 쿠키 기능 및 실패 카드 자동 재분석 단위/통합 테스트."""

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox

from chzzk_downloader.core.cookie_manager import (
    clear_cookies,
    export_cookie_file,
    get_cookie_status_summary,
    get_cookies_text,
    has_valid_cookies,
    load_cookie_file,
    parse_cookie_text,
    save_cookies_text,
    set_custom_cookie_path,
)
from chzzk_downloader.core.ytdlp import (
    VodFormatInfo,
    VodInfo,
    extract_vod_info,
)
from chzzk_downloader.gui.cookie_viewer_dialog import CookieViewerDialog
from chzzk_downloader.gui.main_window import MainWindow
from chzzk_downloader.gui.settings_window import SettingsWindow
from chzzk_downloader.gui.task_card import TaskCardWidget, TaskStatus


@pytest.fixture(autouse=True)
def setup_test_cookie_path(tmp_path):
    """테스트 실행 시 격리된 임시 쿠키 파일 경로를 사용하도록 설정."""
    cookie_file = tmp_path / "test_cookies.txt"
    set_custom_cookie_path(cookie_file)
    yield cookie_file
    set_custom_cookie_path(None)


@pytest.fixture
def main_window(qtbot):
    """메인 창 인스턴스를 생성하고 표시하는 fixture."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    return window


def test_parse_cookie_text_netscape_valid():
    """Netscape HTTP Cookie 포맷 파싱 및 필수 키(NID_AUT/NID_SES) 검증."""
    netscape_sample = (
        "# Netscape HTTP Cookie File\n"
        ".naver.com\tTRUE\t/\tFALSE\t2147483647\tNID_AUT\taut_token_123\n"
        ".naver.com\tTRUE\t/\tFALSE\t2147483647\tNID_SES\tses_token_456\n"
    )
    ok, content, msg = parse_cookie_text(netscape_sample)
    assert ok is True
    assert "NID_AUT" in content
    assert "NID_SES" in content
    assert "유효한 Netscape" in msg


def test_parse_cookie_text_raw_header_valid():
    """HTTP Raw Header 문자열(NID_AUT=...; NID_SES=...)의 Netscape 자동 변환 검증."""
    raw_header = "NID_AUT=aut_value_999; NID_SES=ses_value_888; other_cookie=xyz"
    ok, content, msg = parse_cookie_text(raw_header)
    assert ok is True
    assert content.startswith("# Netscape HTTP Cookie File")
    assert "NID_AUT\taut_value_999" in content
    assert "NID_SES\tses_value_888" in content
    assert "성공:" in msg


def test_parse_cookie_text_invalid_missing_keys():
    """필수 쿠키(NID_AUT 또는 NID_SES)가 누락된 경우 유효성 검사 실패 검증."""
    # 1. 빈 값
    ok, _, msg = parse_cookie_text("")
    assert ok is False
    assert "비어 있습니다" in msg

    # 2. 필수 키가 없는 다른 쿠키
    ok, _, msg = parse_cookie_text("SOME_OTHER_KEY=12345; ANOTHER=67890")
    assert ok is False
    assert "필수 쿠키" in msg


def test_save_and_get_and_clear_cookies(setup_test_cookie_path):
    """쿠키 저장, 조회, 유효성 확인, 상태 요약 및 초기화(삭제) 동작 검증."""
    cookie_path = setup_test_cookie_path

    # 초기 상태
    assert has_valid_cookies(cookie_path) is False
    assert get_cookie_status_summary(cookie_path) == "등록된 쿠키 없음"
    assert get_cookies_text(cookie_path) == ""

    # 저장
    raw_cookie = "NID_AUT=test_aut; NID_SES=test_ses"
    ok, msg = save_cookies_text(raw_cookie, cookie_path)
    assert ok is True
    assert cookie_path.is_file()
    assert has_valid_cookies(cookie_path) is True
    assert "NID_AUT, NID_SES 확인" in get_cookie_status_summary(cookie_path)

    # 내용 조회
    saved_text = get_cookies_text(cookie_path)
    assert "NID_AUT\ttest_aut" in saved_text

    # 초기화
    clear_cookies(cookie_path)
    assert not cookie_path.exists()
    assert has_valid_cookies(cookie_path) is False
    assert get_cookie_status_summary(cookie_path) == "등록된 쿠키 없음"


def test_export_and_load_cookie_file(setup_test_cookie_path, tmp_path):
    """쿠키 파일 내보내기 및 외부 파일로부터 불러오기 동작 검증."""
    # 1. 쿠키 저장
    save_cookies_text("NID_AUT=export_aut; NID_SES=export_ses")

    # 2. 내보내기
    export_target = tmp_path / "exported_cookies.txt"
    ok, msg = export_cookie_file(export_target)
    assert ok is True
    assert export_target.is_file()
    assert "NID_AUT\texport_aut" in export_target.read_text(encoding="utf-8")

    # 3. 초기화
    clear_cookies()
    assert has_valid_cookies() is False

    # 4. 내보낸 파일로부터 불러오기
    ok, msg = load_cookie_file(export_target)
    assert ok is True
    assert has_valid_cookies() is True
    assert "NID_AUT\texport_aut" in get_cookies_text()


def test_cookie_viewer_dialog_save_and_cancel(qtbot):
    """CookieViewerDialog에서 텍스트 입력 후 저장 및 취소 동작 검증."""
    dialog = CookieViewerDialog()
    qtbot.addWidget(dialog)

    # 1. 유효하지 않은 입력 시 저장 거부 및 에러 피드백
    dialog.text_edit.setPlainText("OTHER_KEY=value_without_nid")
    dialog._on_save_clicked()
    assert dialog.feedback_label.isHidden() is False
    assert "필수 쿠키" in dialog.feedback_label.text()

    # 2. 유효한 입력 시 저장 성공
    dialog.text_edit.setPlainText("NID_AUT=modal_aut; NID_SES=modal_ses")
    with qtbot.waitSignal(dialog.accepted, timeout=1000):
        dialog._on_save_clicked()

    assert has_valid_cookies() is True
    assert "NID_AUT\tmodal_aut" in get_cookies_text()


def test_settings_window_modeless_and_actions(qtbot, tmp_path):
    """SettingsWindow의 Modeless 동작, 상태 표시, 보기/내보내기/초기화 액션 검증."""
    window = SettingsWindow()
    qtbot.addWidget(window)
    assert window.isModal() is False

    # 초기 상태
    assert "등록된 쿠키 없음" in window.status_label.text()

    # 쿠키 저장 후 상태 갱신 확인
    save_cookies_text("NID_AUT=set_aut; NID_SES=set_ses")
    window.refresh_status()
    assert "NID_AUT, NID_SES 확인" in window.status_label.text()

    # 파일 불러오기 테스트
    cookie_txt = tmp_path / "imported.txt"
    cookie_txt.write_text(
        ".naver.com\tTRUE\t/\tTRUE\t2147483647\tNID_AUT\timported_aut\n",
        encoding="utf-8",
    )
    with patch(
        "PyQt6.QtWidgets.QFileDialog.getOpenFileName",
        return_value=(str(cookie_txt), "txt"),
    ):
        with patch.object(QMessageBox, "information"):
            with qtbot.waitSignal(window.cookies_updated, timeout=1000):
                window._on_import_file()
    assert has_valid_cookies() is True
    assert "NID_AUT 확인" in window.status_label.text()

    # 초기화 클릭 (QMessageBox Yes 모킹)
    with patch.object(
        QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
    ):
        with patch.object(QMessageBox, "information"):
            with qtbot.waitSignal(window.cookies_updated, timeout=1000):
                window._on_clear_clicked()

    assert has_valid_cookies() is False
    assert "등록된 쿠키 없음" in window.status_label.text()


def test_main_window_settings_button_opens_modeless_window(main_window, qtbot):
    """메인 창 상단 설정 버튼 클릭 시 Modeless 설정 창이 정상적으로 열리는지 검증."""
    qtbot.mouseClick(main_window.settings_btn, Qt.MouseButton.LeftButton)

    assert hasattr(main_window, "_settings_window")
    assert main_window._settings_window is not None
    assert main_window._settings_window.isVisible() is True
    assert main_window._settings_window.isModal() is False

    # 다시 클릭 시에도 새 창이 중복 생성되지 않고 기존 창 유지
    existing = main_window._settings_window
    qtbot.mouseClick(main_window.settings_btn, Qt.MouseButton.LeftButton)
    assert main_window._settings_window is existing


def test_task_card_auth_buttons_distinct_actions(main_window, qtbot):
    """로그인 필요 카드의 [쿠키 설정]은 설정창을 열고, [네이버 로그인]은 로그인 다이얼로그를 트리거하는지 검증."""
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/19000",
        status=TaskStatus.FAILED_LOGIN_REQUIRED,
    )
    main_window.task_list_widget.add_task_card(card)

    # 1. [쿠키 설정] 클릭 -> Modeless 설정 창 열림
    qtbot.mouseClick(card.cookie_btn, Qt.MouseButton.LeftButton)
    assert main_window._settings_window is not None
    assert main_window._settings_window.isVisible() is True
    main_window._settings_window.close()

    # 2. [네이버 로그인] 클릭 -> request_naver_login 시그널 방출 및 NaverLoginDialog.exec 호출 검증
    with patch(
        "chzzk_downloader.gui.naver_login_dialog.NaverLoginDialog.exec"
    ) as mock_exec:
        with qtbot.waitSignal(card.request_naver_login, timeout=1000):
            qtbot.mouseClick(card.login_btn, Qt.MouseButton.LeftButton)
        assert mock_exec.called is True


def test_save_network_cookies_and_naver_login_dialog(setup_test_cookie_path, qtbot):
    """save_network_cookies 함수 및 NaverLoginDialog 쿠키 감지·완료 로직 검증."""
    from PyQt6.QtCore import QByteArray
    from PyQt6.QtNetwork import QNetworkCookie

    from chzzk_downloader.core.cookie_manager import save_network_cookies
    from chzzk_downloader.gui.naver_login_dialog import NaverLoginDialog

    # 1. save_network_cookies 검증
    cookie_aut = QNetworkCookie(QByteArray(b"NID_AUT"), QByteArray(b"test_net_aut"))
    cookie_aut.setDomain(".naver.com")
    cookie_aut.setPath("/")
    cookie_aut.setSecure(True)

    cookie_ses = QNetworkCookie(QByteArray(b"NID_SES"), QByteArray(b"test_net_ses"))
    cookie_ses.setDomain(".naver.com")
    cookie_ses.setPath("/")

    cookie_other = QNetworkCookie(QByteArray(b"OTHER"), QByteArray(b"val"))
    cookie_other.setDomain(".google.com")

    # 인증 쿠키 없을 때 실패
    ok, err = save_network_cookies([cookie_other])
    assert ok is False
    assert "감지되지 않았습니다" in err

    # 유효 쿠키 저장 성공
    ok, msg = save_network_cookies([cookie_aut, cookie_ses, cookie_other])
    assert ok is True
    assert "저장되었습니다" in msg
    assert has_valid_cookies() is True
    assert "test_net_aut" in get_cookies_text()

    # 2. NaverLoginDialog 이벤트 핸들러 검증
    with patch("PyQt6.QtWebEngineWidgets.QWebEngineView.load"):
        dialog = NaverLoginDialog()
        qtbot.addWidget(dialog)
        assert dialog.save_btn.isEnabled() is False

        # 쿠키 추가 이벤트 시뮬레이션
        dialog._on_cookie_added(cookie_aut)
        assert dialog.save_btn.isEnabled() is True
        assert "인증 정보가 감지되었습니다" in dialog.status_label.text()

        # 저장 및 닫기 호출 시 시그널 방출 확인
        with qtbot.waitSignal(dialog.login_success, timeout=1000):
            dialog._on_save_and_close()


def test_main_window_auto_reanalyze_failed_login_cards_on_cookie_update(
    main_window, qtbot
):
    """쿠키 등록 완료 시 로그인 필요 실패 카드들이 자동으로 재분석(ANALYZING -> READY)되는지 검증 (옵션 A)."""
    # 1. 실패 카드 등록
    card = TaskCardWidget(
        raw_url="https://chzzk.naver.com/video/15021267",
        status=TaskStatus.FAILED_LOGIN_REQUIRED,
    )
    main_window.task_list_widget.add_task_card(card)
    assert card.status == TaskStatus.FAILED_LOGIN_REQUIRED

    # 2. 쿠키 저장
    save_cookies_text("NID_AUT=auto_reanalyze_aut; NID_SES=auto_reanalyze_ses")

    mock_vod = VodInfo(
        video_no="15021267",
        video_title="성인 인증 완료 방송",
        channel_name="스트리머D",
        duration=3600,
        formats=[VodFormatInfo(format_id="1080p", height=1080, fps=60.0)],
        live_open_date="2024-05-06",
    )

    with patch("chzzk_downloader.gui.workers.extract_vod_info", return_value=mock_vod):
        # 쿠키 갱신 이벤트 트리거
        main_window._on_cookies_updated()

        # T02 토스트는 침묵(미노출) 처리되고 백그라운드에서 자동 재분석 진행
        assert main_window.toast.isHidden() is True

        # 카드가 ANALYZING을 거쳐 READY 상태로 전환되는지 대기
        qtbot.waitUntil(lambda: card.status == TaskStatus.READY, timeout=2000)
        assert card.title_label.text() == "[스트리머D] 2024-05-06 성인 인증 완료 방송"


def test_ytdlp_extract_vod_info_includes_cookiefile(setup_test_cookie_path):
    """유효 쿠키가 존재할 때 extract_vod_info가 yt-dlp에 cookiefile 인자를 전달하는지 검증."""
    save_cookies_text("NID_AUT=ytdlp_aut; NID_SES=ytdlp_ses")
    cookie_file = setup_test_cookie_path

    mock_raw_data = {
        "id": "15016450",
        "title": "쿠키 전달 테스트 영상",
        "uploader": "테스트채널",
        "duration": 100,
        "formats": [{"format_id": "1080p", "height": 1080}],
    }

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = mock_raw_data

    with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

        info = extract_vod_info("https://chzzk.naver.com/video/15016450")
        assert info.video_title == "쿠키 전달 테스트 영상"

        # ytdlp 생성 시 전달된 옵션 검증
        call_opts = mock_ydl_cls.call_args[0][0]
        assert "cookiefile" in call_opts
        assert call_opts["cookiefile"] == str(cookie_file)
