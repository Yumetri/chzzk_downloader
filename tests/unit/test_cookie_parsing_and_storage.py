"""Netscape 쿠키 파싱, HTTP 헤더 변환, 파일 입출력, 보안 권한 및 세션 검증 단위 테스트."""

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtNetwork import QNetworkCookie

from chzzk_downloader.core.cookie_manager import (
    SessionStatus,
    clear_cookies,
    export_cookie_file,
    get_cookie_status_summary,
    get_cookies_text,
    has_valid_cookies,
    load_cookie_file,
    parse_cookie_text,
    save_cookies_text,
    save_network_cookies,
    set_custom_cookie_path,
    verify_cookie_session,
)
from chzzk_downloader.gui.workers import CookieVerifyWorker


@pytest.mark.ticket("T0106")
def test_parse_cookie_text_netscape_valid() -> None:
    """[T0106] Netscape HTTP Cookie 포맷 파싱 및 필수 키(NID_AUT/NID_SES) 검증."""
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


@pytest.mark.ticket("T0106")
def test_parse_cookie_text_raw_header_valid() -> None:
    """[T0106] HTTP Raw Header 문자열(NID_AUT=...; NID_SES=...)의 Netscape 자동 변환 검증."""
    raw_header = "NID_AUT=aut_value_999; NID_SES=ses_value_888; other_cookie=xyz"
    ok, content, msg = parse_cookie_text(raw_header)
    assert ok is True
    assert content.startswith("# Netscape HTTP Cookie File")
    assert "NID_AUT\taut_value_999" in content
    assert "NID_SES\tses_value_888" in content
    assert "성공:" in msg


@pytest.mark.ticket("T0106")
def test_parse_cookie_text_invalid_missing_keys() -> None:
    """[T0106] 필수 쿠키(NID_AUT 또는 NID_SES)가 누락된 경우 유효성 검사 실패 검증."""
    ok1, _, msg1 = parse_cookie_text("")
    assert ok1 is False
    assert "비어 있습니다" in msg1

    ok2, _, msg2 = parse_cookie_text("SOME_OTHER_KEY=12345; ANOTHER=67890")
    assert ok2 is False
    assert "필수 쿠키" in msg2


@pytest.mark.ticket("T0106")
def test_save_and_get_and_clear_cookies(tmp_path: Path) -> None:
    """[T0106] 쿠키 저장, 조회, 유효성 확인, 상태 요약 및 초기화(삭제) 동작 검증."""
    cookie_path = tmp_path / "custom_cookies.txt"

    assert has_valid_cookies(cookie_path) is False
    assert get_cookie_status_summary(cookie_path) == "등록된 쿠키 없음"
    assert get_cookies_text(cookie_path) == ""

    raw_cookie = "NID_AUT=test_aut; NID_SES=test_ses"
    ok, msg = save_cookies_text(raw_cookie, cookie_path)
    assert ok is True
    assert cookie_path.is_file()
    assert has_valid_cookies(cookie_path) is True
    assert "NID_AUT, NID_SES 확인" in get_cookie_status_summary(cookie_path)

    saved_text = get_cookies_text(cookie_path)
    assert "NID_AUT\ttest_aut" in saved_text

    clear_cookies(cookie_path)
    assert not cookie_path.exists()
    assert has_valid_cookies(cookie_path) is False
    assert get_cookie_status_summary(cookie_path) == "등록된 쿠키 없음"


@pytest.mark.ticket("T0106")
def test_export_and_load_cookie_file(tmp_path: Path) -> None:
    """[T0106] 쿠키 파일 내보내기 및 외부 파일로부터 불러오기 동작 검증."""
    save_cookies_text("NID_AUT=export_aut; NID_SES=export_ses")

    export_target = tmp_path / "exported_cookies.txt"
    ok, msg = export_cookie_file(export_target)
    assert ok is True
    assert export_target.is_file()
    assert "NID_AUT\texport_aut" in export_target.read_text(encoding="utf-8")

    clear_cookies()
    assert has_valid_cookies() is False

    ok, msg = load_cookie_file(export_target)
    assert ok is True
    assert has_valid_cookies() is True
    assert "NID_AUT\texport_aut" in get_cookies_text()


@pytest.mark.ticket("T0106")
def test_cookie_file_secure_permissions() -> None:
    """[T0106] 쿠키 파일 저장 시 0600, 부모 디렉터리는 0700 퍼미션 설정이 호출되는지 검증."""
    with patch.object(Path, "chmod") as mock_chmod:
        save_cookies_text("NID_AUT=test_perm_aut; NID_SES=test_perm_ses")
        chmod_calls = [call[0][0] for call in mock_chmod.call_args_list]
        assert 0o700 in chmod_calls or 0o600 in chmod_calls

    cookie_obj = QNetworkCookie(b"NID_AUT", b"val")
    cookie_obj.setDomain(".naver.com")
    cookie_obj.setPath("/")

    with patch.object(Path, "chmod") as mock_chmod:
        save_network_cookies([cookie_obj])
        chmod_calls = [call[0][0] for call in mock_chmod.call_args_list]
        assert 0o700 in chmod_calls or 0o600 in chmod_calls


@pytest.mark.ticket("T0107")
def test_verify_cookie_session_no_cookies() -> None:
    """[T0107] 쿠키 파일이 없거나 비어있는 경우 NO_COOKIES 반환 검증."""
    status, msg = verify_cookie_session()
    assert status == SessionStatus.NO_COOKIES
    assert "등록된 쿠키 없음" in msg


@pytest.mark.ticket("T0107")
def test_verify_cookie_session_valid_200() -> None:
    """[T0107] 치지직 API 200 OK 및 닉네임 반환 시 VALID 상태 및 최근 확인 시각 갱신 검증."""
    save_cookies_text("NID_AUT=aut_valid; NID_SES=ses_valid")

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"code": 200, "content": {"nickname": "치지직유저"}}
    ).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        status, msg = verify_cookie_session()
        assert status == SessionStatus.VALID
        assert "치지직유저" in msg
        assert "최근 확인" in msg

        summary = get_cookie_status_summary()
        assert "치지직유저" in summary


@pytest.mark.ticket("T0107")
def test_verify_cookie_session_expired_401() -> None:
    """[T0107] 치지직 API 401 Unauthorized 반환 시 EXPIRED 상태 검증."""
    save_cookies_text("NID_AUT=aut_expired; NID_SES=ses_expired")

    err = urllib.error.HTTPError(
        url="https://comm-api.game.naver.com/nng_main/v1/user/getUserStatus",
        code=401,
        msg="Unauthorized",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b'{"code": 401, "message": "Unauthorized"}'),
    )

    with patch("urllib.request.urlopen", side_effect=err):
        status, msg = verify_cookie_session()
        assert status == SessionStatus.EXPIRED
        assert "만료됨" in msg

        summary = get_cookie_status_summary()
        assert "만료됨" in summary


@pytest.mark.ticket("T0107")
def test_verify_cookie_session_logged_in_false() -> None:
    """[T0107] API 응답은 200이나 loggedIn이 false인 경우 세션 만료(EXPIRED) 처리 검증."""
    save_cookies_text("NID_AUT=aut_expired; NID_SES=ses_expired")

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"code": 200, "content": {"loggedIn": False, "nickname": None}}
    ).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        status, msg = verify_cookie_session()
        assert status == SessionStatus.EXPIRED
        assert "만료됨" in msg

        summary = get_cookie_status_summary()
        assert "만료됨" in summary


@pytest.mark.ticket("T0107")
def test_verify_cookie_session_network_error() -> None:
    """[T0107] 타임아웃 또는 네트워크 연결 불가 시 NETWORK_ERROR 상태 반환 검증."""
    save_cookies_text("NID_AUT=aut_val; NID_SES=ses_val")

    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("Connection refused"),
    ):
        status, msg = verify_cookie_session()
        assert status == SessionStatus.NETWORK_ERROR
        assert "네트워크 연결 실패" in msg


@pytest.mark.ticket("T0107")
def test_cookie_verify_worker_thread(qtbot) -> None:
    """[T0107] CookieVerifyWorker QThread가 백그라운드에서 실행되고 시그널을 방출하는지 검증."""
    save_cookies_text("NID_AUT=aut_thread; NID_SES=ses_thread")

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"code": 200, "content": {"nickname": "워커유저"}}
    ).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    worker = CookieVerifyWorker()
    with patch("urllib.request.urlopen", return_value=mock_resp):
        with qtbot.waitSignal(worker.finished_verification, timeout=1000) as blocker:
            worker.start()

        assert blocker.args[0] == SessionStatus.VALID
        assert "워커유저" in blocker.args[1]


@pytest.mark.ticket("T0106")
def test_cookie_file_corrupted_and_binary_garbage_handling(tmp_path: Path) -> None:
    """[T0106] 깨진 파일, 빈 파일, 바이너리 쓰레기 데이터 파일 로드 시 안전한 실패 처리 검증."""
    # 1. 존재하지 않는 파일 로드
    ok, msg = load_cookie_file(tmp_path / "non_existent.txt")
    assert ok is False
    assert "존재하지 않습니다" in msg

    # 2. 빈 파일 로드
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")
    ok, msg = load_cookie_file(empty_file)
    assert ok is False
    assert "비어 있습니다" in msg

    # 3. 임의의 텍스트지만 인증 쿠키가 없는 파일
    no_auth_file = tmp_path / "no_auth.txt"
    no_auth_file.write_text(
        ".naver.com\tTRUE\t/\tTRUE\t2147483647\tOTHER\tvalue\n", encoding="utf-8"
    )
    ok, msg = load_cookie_file(no_auth_file)
    assert ok is False
    assert "NID_AUT" in msg

    # 4. 바이너리 쓰레기 데이터 파일 로드
    binary_file = tmp_path / "garbage.bin"
    binary_file.write_bytes(b"\x00\xff\xfe\x01\x02\x03\x80\x90\xaa\xbb")
    ok, msg = load_cookie_file(binary_file)
    assert ok is False


@pytest.mark.ticket("T0106")
def test_cookie_manager_clear_cookies_when_already_missing(tmp_path: Path) -> None:
    """[T0106] 쿠키 파일이 이미 존재하지 않는 상태에서 clear_cookies() 호출 시 예외 없이 안전한지 검증."""
    test_file = tmp_path / "cookies_missing.txt"
    set_custom_cookie_path(test_file)
    assert test_file.exists() is False

    clear_cookies()
    assert has_valid_cookies() is False


@pytest.mark.ticket("T0106")
def test_export_cookie_file_permission_error_handling(tmp_path: Path) -> None:
    """[T0106] 내보내기 경로가 디렉터리이거나 쓰기 실패 시 예외 없이 에러 반환 검증."""
    save_cookies_text("NID_AUT=export_test; NID_SES=export_ses")

    # 대상 경로가 기존 디렉터리인 경우 쓰기 오류 발생
    invalid_target = tmp_path / "some_directory"
    invalid_target.mkdir()

    ok, msg = export_cookie_file(invalid_target)
    assert ok is False
    assert "내보내기 실패" in msg
