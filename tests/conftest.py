"""Pytest 전역 설정 및 초기화."""

import PyQt6.QtWebEngineWidgets  # noqa: F401 - QtWebEngine must be imported before QApplication
import pytest

from chzzk_downloader.core.cookie_manager import set_custom_cookie_path


@pytest.fixture(autouse=True)
def isolate_test_cookie_environment(tmp_path):
    """모든 테스트에서 실제 사용자 홈 디렉터리의 쿠키 파일 접근을 격리합니다."""
    isolated_cookie_file = tmp_path / ".chzzk_downloader" / "isolated_cookies.txt"
    set_custom_cookie_path(isolated_cookie_file)
    yield
    set_custom_cookie_path(None)
