"""T0103. yt-dlp 기반 VOD 정보 조회 및 예외 처리 단위 테스트."""

from unittest.mock import MagicMock, patch

import pytest
from yt_dlp.utils import DownloadError

from chzzk_downloader.core.ytdlp import (
    VodFormatInfo,
    VodInfo,
    VodNotFoundError,
    YtDlpError,
    YtDlpNotInstalledError,
    extract_vod_info,
    get_ytdlp_version,
)
from chzzk_downloader.gui.workers import VodCheckWorker


def test_get_ytdlp_version_success():
    """설치된 yt-dlp 버전을 정상적으로 반환하는지 검증."""
    version = get_ytdlp_version()
    assert isinstance(version, str)
    assert len(version) > 0


def test_get_ytdlp_version_failure():
    """yt-dlp 버전을 가져올 수 없을 때 YtDlpNotInstalledError가 발생하는지 검증."""
    with patch("yt_dlp.version.__version__", None):
        with pytest.raises(
            YtDlpNotInstalledError, match="yt-dlp 버전을 확인할 수 없습니다"
        ):
            get_ytdlp_version()


def test_extract_vod_info_success():
    """yt-dlp 추출 결과로부터 VodInfo 및 VodFormatInfo 모델이 올바르게 생성되는지 검증."""
    mock_data = {
        "id": "15016450",
        "title": "테스트 방송 VOD 다시보기",
        "channel": "테스트채널",
        "thumbnail": "https://example.com/thumb.jpg",
        "duration": 3600,
        "formats": [
            {
                "format_id": "1080p",
                "resolution": "1920x1080",
                "width": 1920,
                "height": 1080,
                "fps": 60,
                "tbr": 8000.0,
                "url": "https://example.com/1080p.m3u8",
            },
            {
                "format_id": "720p",
                "resolution": "1280x720",
                "width": 1280,
                "height": 720,
                "fps": 30,
                "tbr": 4000.0,
                "url": "https://example.com/720p.m3u8",
            },
            "invalid_format_entry",  # 비정상 포맷 엔트리 무시 검증
        ],
    }

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = mock_data
    mock_ydl.__enter__.return_value = mock_ydl

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        info = extract_vod_info("https://chzzk.naver.com/video/15016450")

        assert isinstance(info, VodInfo)
        assert info.video_no == "15016450"
        assert info.video_title == "테스트 방송 VOD 다시보기"
        assert info.channel_name == "테스트채널"
        assert info.thumbnail_url == "https://example.com/thumb.jpg"
        assert info.duration == 3600
        assert len(info.formats) == 2

        f1 = info.formats[0]
        assert isinstance(f1, VodFormatInfo)
        assert f1.format_id == "1080p"
        assert f1.resolution == "1920x1080"
        assert f1.width == 1920
        assert f1.height == 1080
        assert f1.fps == 60
        assert f1.tbr == 8000.0
        assert f1.url == "https://example.com/1080p.m3u8"


def test_extract_vod_info_parses_live_open_date_with_hours_and_minutes():
    """live_open_date 문자열(YYYY-MM-DD HH:MM:SS)에서 초를 제외하고 시:분까지 추출하는지 검증."""
    mock_data = {
        "id": "15368883",
        "title": "잠시 에반게리온 분석방",
        "uploader": "소풍왔니",
        "live_open_date": "2026-09-25 10:32:44",
        "formats": [],
    }

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = mock_data
    mock_ydl.__enter__.return_value = mock_ydl

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        info = extract_vod_info("https://chzzk.naver.com/video/15368883")
        assert info.live_open_date == "2026-09-25 10:32"


def test_extract_vod_info_fallback_channel_and_defaults():
    """channel 누락 시 uploader 사용 및 기본값 처리가 올바른지 검증."""
    mock_data = {
        "id": "12345",
        "uploader": "업로더스트리머",
        "formats": [],
    }

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = mock_data
    mock_ydl.__enter__.return_value = mock_ydl

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        info = extract_vod_info("https://chzzk.naver.com/video/12345")
        assert info.video_no == "12345"
        assert info.channel_name == "업로더스트리머"
        assert info.video_title == "제목 없음"
        assert info.duration == 0
        assert info.formats == []


def test_extract_vod_info_empty_data_raises_not_found():
    """yt-dlp 반환 데이터가 비어있을 때 VodNotFoundError 발생 검증."""
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = None
    mock_ydl.__enter__.return_value = mock_ydl

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        with pytest.raises(VodNotFoundError, match="동영상 정보를 가져올 수 없습니다"):
            extract_vod_info("https://chzzk.naver.com/video/99999")


@pytest.mark.parametrize(
    "error_msg",
    [
        "HTTP Error 404: Not Found",
        "Video not found",
        "존재하지 않는 동영상입니다.",
        "This video is unavailable",
    ],
)
def test_extract_vod_info_download_error_404_raises_not_found(error_msg: str):
    """삭제되었거나 존재하지 않는 동영상 에러 발생 시 VodNotFoundError로 변환되는지 검증."""
    mock_ydl = MagicMock()
    mock_ydl.extract_info.side_effect = DownloadError(error_msg)
    mock_ydl.__enter__.return_value = mock_ydl

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        with pytest.raises(VodNotFoundError, match="존재하지 않습니다"):
            extract_vod_info("https://chzzk.naver.com/video/99999")


def test_extract_vod_info_network_or_general_download_error():
    """네트워크 또는 일반 DownloadError 발생 시 YtDlpError로 변환되는지 검증."""
    mock_ydl = MagicMock()
    mock_ydl.extract_info.side_effect = DownloadError(
        "Network connection reset by peer"
    )
    mock_ydl.__enter__.return_value = mock_ydl

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        with pytest.raises(YtDlpError, match="yt-dlp 영상 정보 추출 실패"):
            extract_vod_info("https://chzzk.naver.com/video/123")


def test_extract_vod_info_unexpected_exception():
    """기타 예기치 못한 Exception 발생 시 YtDlpError로 변환되는지 검증."""
    mock_ydl = MagicMock()
    mock_ydl.extract_info.side_effect = RuntimeError("Unexpected internal crash")
    mock_ydl.__enter__.return_value = mock_ydl

    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        with pytest.raises(YtDlpError, match="yt-dlp 실행 오류"):
            extract_vod_info("https://chzzk.naver.com/video/123")


def test_vod_check_worker_success(qtbot):
    """VodCheckWorker가 정상 추출 시 finished_success 시그널을 방출하는지 검증."""
    mock_info = VodInfo(
        video_no="15016450",
        video_title="성공 테스트",
        channel_name="스트리머",
    )

    worker = VodCheckWorker("15016450")
    with patch(
        "chzzk_downloader.gui.workers.extract_vod_info", return_value=mock_info
    ) as mock_extract:
        with qtbot.waitSignal(worker.finished_success, timeout=1000) as blocker:
            worker.start()

        assert blocker.args[0] == mock_info
        mock_extract.assert_called_once_with("https://chzzk.naver.com/video/15016450")


def test_vod_check_worker_url_input_preserved(qtbot):
    """VodCheckWorker에 전체 URL이 입력되었을 때 URL을 그대로 사용하는지 검증."""
    mock_info = VodInfo(video_no="999", video_title="URL 보존", channel_name="채널")
    full_url = "https://chzzk.naver.com/video/999"

    worker = VodCheckWorker(full_url)
    with patch(
        "chzzk_downloader.gui.workers.extract_vod_info", return_value=mock_info
    ) as mock_extract:
        with qtbot.waitSignal(worker.finished_success, timeout=1000):
            worker.start()

        mock_extract.assert_called_once_with(full_url)


def test_vod_check_worker_not_found_failure(qtbot):
    """VodCheckWorker가 VodNotFoundError 발생 시 finished_failed 시그널을 방출하는지 검증."""
    worker = VodCheckWorker("99999")
    with patch(
        "chzzk_downloader.gui.workers.extract_vod_info",
        side_effect=VodNotFoundError("동영상 정보가 존재하지 않습니다."),
    ):
        with qtbot.waitSignal(worker.finished_failed, timeout=1000) as blocker:
            worker.start()

        assert "동영상 정보가 존재하지 않습니다." in blocker.args[0]


def test_vod_check_worker_general_error_failure(qtbot):
    """VodCheckWorker가 YtDlpError 발생 시 finished_failed 시그널을 방출하는지 검증."""
    worker = VodCheckWorker("99999")
    with patch(
        "chzzk_downloader.gui.workers.extract_vod_info",
        side_effect=YtDlpError("yt-dlp 영상 정보 추출 실패: 타임아웃"),
    ):
        with qtbot.waitSignal(worker.finished_failed, timeout=1000) as blocker:
            worker.start()

        assert "yt-dlp 영상 정보 추출 실패: 타임아웃" in blocker.args[0]
