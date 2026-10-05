"""yt-dlp VOD 다운로드 실행 옵션 빌더 모듈."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from chzzk_downloader.config import DEFAULT_USER_AGENT
from chzzk_downloader.core.task_models import TaskSpec
from chzzk_downloader.core.ytdlp import prepare_ytdlp_ffmpeg


def build_vod_download_opts(task_spec: TaskSpec) -> dict[str, Any]:
    """TaskSpec으로부터 yt-dlp 다운로드 옵션을 빌드합니다.

    - 네이버 LiveCloud CDN 400 차단 방어 (Referer, User-Agent)
    - 최신 FFmpeg(v6.1+)의 .m4v 거부 방어 (-extension_picky 0, -allowed_extensions ALL)
    - 쿠키 세션 및 컨테이너 리먹스(mp4 등) 옵션 주입
    - 구간 다운로드 (download_ranges) 옵션 주입
    """
    save_path = Path(task_spec.save_path)
    save_dir = save_path.parent
    ext = task_spec.selected_ext or "mp4"

    # 화질 선택 포맷 문자열
    quality = task_spec.selected_quality
    if quality and quality.lower() not in ("best", "최고 화질", "최고화질"):
        format_str = (
            f"bestvideo[format_id*={quality}]+bestaudio/"
            f"best[format_id*={quality}]/bestvideo+bestaudio/best"
        )
    else:
        format_str = "bestvideo+bestaudio/best"

    from chzzk_downloader.core.cookie_manager import (
        get_cookie_file_path,
        has_valid_cookies,
    )
    from chzzk_downloader.core.ffmpeg_manager import (
        get_ffmpeg_compatible_args,
        get_ffmpeg_path,
    )

    ffmpeg_bin = get_ffmpeg_path()
    compat_args = get_ffmpeg_compatible_args(ffmpeg_bin) or [
        "-extension_picky",
        "0",
        "-allowed_extensions",
        "ALL",
    ]

    escaped_stem = save_path.stem.replace("%", "%%")
    opts: dict[str, Any] = {
        "format": format_str,
        "outtmpl": {"default": str(save_dir / f"{escaped_stem}.%(ext)s")},
        "remuxvideo": ext,
        "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": ext}],
        "http_headers": {
            "Referer": "https://chzzk.naver.com/",
            "User-Agent": DEFAULT_USER_AGENT,
        },
        "postprocessor_args": {"ffmpeg": compat_args},
        "downloader_args": {"ffmpeg": compat_args},
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": False,
        "nopart": True,
        "continuedl": True,
        "socket_timeout": 30,
        "retries": 10,
        "fragment_retries": 15,
        "extractor_retries": 10,
        "file_access_retries": 5,
    }

    prepare_ytdlp_ffmpeg()
    if ffmpeg_bin:
        opts["ffmpeg_location"] = str(ffmpeg_bin)

    if has_valid_cookies():
        opts["cookiefile"] = str(get_cookie_file_path())

    if task_spec.section_start is not None or task_spec.section_end is not None:
        from yt_dlp.utils import download_range_func

        s_start = (
            task_spec.section_start if task_spec.section_start is not None else 0.0
        )
        opts["download_ranges"] = cast(Any, download_range_func)(
            [], [(s_start, task_spec.section_end)]
        )
        section_ffmpeg_args = list(compat_args)
        if "-avoid_negative_ts" not in section_ffmpeg_args:
            section_ffmpeg_args.extend(["-avoid_negative_ts", "make_zero"])
        opts["postprocessor_args"] = {"ffmpeg": section_ffmpeg_args}
        opts["downloader_args"] = {"ffmpeg": section_ffmpeg_args}

    return opts
