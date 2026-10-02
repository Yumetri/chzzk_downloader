"""파일명 정제, 전각 콜론 치환, 파일명 템플릿 및 중복 회피 단위 테스트."""

from pathlib import Path

import pytest

from chzzk_downloader.core.filename_generator import (
    generate_vod_filename,
    resolve_duplicate_filename,
    sanitize_filename,
)
from chzzk_downloader.core.ytdlp import VodInfo


@pytest.mark.ticket("T0109")
def test_sanitize_filename_converts_colon() -> None:
    """[T0109] 콜론을 전각 콜론으로 치환하고 Windows 금지 문자를 정제하는지 검증."""
    raw = '방송: 다시보기? <1> / 테스트 * | "호환"'
    sanitized = sanitize_filename(raw)
    assert ":" not in sanitized
    assert "：" in sanitized  # 전각 콜론
    assert "?" not in sanitized
    assert "<" not in sanitized
    assert ">" not in sanitized
    assert "/" not in sanitized
    assert "*" not in sanitized
    assert "|" not in sanitized
    assert '"' not in sanitized


@pytest.mark.ticket("T0109")
def test_generate_vod_filename_with_and_without_live_date() -> None:
    """[T0109] live_open_date 유무에 따른 파일명 명명 규칙 검증."""
    info_with_date = VodInfo(
        video_no="12345",
        video_title="테스트: 라이브",
        channel_name="스트리머A",
        live_open_date="2024-05-06",
    )
    name1 = generate_vod_filename(info_with_date, ext=".mp4")
    assert "date：2024-05-06" in name1
    assert "스트리머A" in name1

    info_without_date = VodInfo(
        video_no="67890",
        video_title="일반 영상",
        channel_name="스트리머B",
        live_open_date="",
    )
    name2 = generate_vod_filename(info_without_date, ext=".ts")
    assert name2 == "[스트리머B] 일반 영상 (67890).ts"


@pytest.mark.ticket("T0109")
def test_resolve_duplicate_filename(tmp_path: Path) -> None:
    """[T0109] 동일 파일이 존재할 경우 (1), (2) 넘버링된 고유 경로 반환 검증."""
    base_file = tmp_path / "video.mp4"
    base_file.touch()

    res1 = resolve_duplicate_filename(base_file)
    assert res1.name == "video (1).mp4"

    res1.touch()
    res2 = resolve_duplicate_filename(base_file)
    assert res2.name == "video (2).mp4"
