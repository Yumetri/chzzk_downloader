"""치지직 VOD URL 파싱 및 동영상 ID 추출 단위 테스트."""

import pytest

from chzzk_downloader.core.url_parser import parse_chzzk_vod_url


@pytest.mark.ticket("T0102")
@pytest.mark.parametrize(
    "input_url, expected_id",
    [
        ("https://chzzk.naver.com/video/15016450", "15016450"),
        ("http://chzzk.naver.com/video/12345", "12345"),
        ("https://www.chzzk.naver.com/video/9999", "9999"),
        ("chzzk.naver.com/video/777", "777"),
        ("https://chzzk.naver.com/video/15016450?t=120", "15016450"),
        ("https://chzzk.naver.com/video/15016450#section", "15016450"),
        ("  https://chzzk.naver.com/video/15016450 \n\t", "15016450"),
    ],
)
def test_parse_valid_chzzk_vod_url(input_url: str, expected_id: str) -> None:
    """[T0102] 정상 치지직 VOD URL에서 정확한 video_no가 추출되는지 검증."""
    assert parse_chzzk_vod_url(input_url) == expected_id


@pytest.mark.ticket("T0102")
@pytest.mark.parametrize(
    "invalid_url",
    [
        "",
        "   ",
        "\n\t",
        "https://youtube.com/watch?v=15016450",
        "https://naver.com",
        "https://chzzk-naver.com/video/15016450",
        "https://fakechzzk.naver.com/video/15016450",
        "https://chzzk.naver.com/video/",
        "https://chzzk.naver.com/video/abc",
        "https://chzzk.naver.com/live/c68b8ef525fb3d2fa146344d84991753",
    ],
)
def test_parse_invalid_url(invalid_url: str) -> None:
    """[T0102] 유효하지 않거나 다른 사이트의 URL은 None을 반환하는지 검증."""
    assert parse_chzzk_vod_url(invalid_url) is None
