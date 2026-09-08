"""Pytest 전역 설정 및 초기화."""

from pathlib import Path

import PyQt6.QtWebEngineWidgets  # noqa: F401 - QtWebEngine must be imported before QApplication
import pytest

from chzzk_downloader.core.cookie_manager import set_custom_cookie_path
from chzzk_downloader.core.ffmpeg_manager import clear_probe_cache
from chzzk_downloader.core.settings_manager import set_custom_settings_path


@pytest.fixture(autouse=True)
def isolate_test_environment(tmp_path: Path):
    """모든 테스트에 대해 settings.json, cookies.txt, FFmpeg 캐시를 자동 격리합니다.

    실제 사용자 홈 디렉터리(~/.chzzk_downloader)의 환경 오염을 완벽히 방지합니다.
    """
    test_settings = tmp_path / "test_settings.json"
    test_cookies = tmp_path / "test_cookies.txt"

    set_custom_settings_path(test_settings)
    set_custom_cookie_path(test_cookies)
    clear_probe_cache()

    yield tmp_path

    set_custom_settings_path(None)
    set_custom_cookie_path(None)
    clear_probe_cache()
