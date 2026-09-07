"""yt-dlp 기반 VOD 메타데이터 조회 모듈."""

from dataclasses import dataclass, field
from typing import Any, cast

import yt_dlp
from yt_dlp.utils import DownloadError


class YtDlpError(Exception):
    """yt-dlp 관련 기본 예외."""


class VodNotFoundError(YtDlpError):
    """VOD 영상이 존재하지 않거나 삭제/비공개 상태일 때 발생하는 예외."""


class YtDlpNotInstalledError(YtDlpError):
    """yt-dlp 라이브러리를 불러올 수 없을 때 발생하는 예외."""


@dataclass
class VodFormatInfo:
    """VOD 개별 화질/스트림 정보."""

    format_id: str
    resolution: str = ""
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    tbr: float | None = None
    url: str = ""


@dataclass
class VodInfo:
    """yt-dlp로 추출한 VOD 메타데이터 모델."""

    video_no: str
    video_title: str
    channel_name: str
    thumbnail_url: str = ""
    duration: int = 0
    formats: list[VodFormatInfo] = field(default_factory=list)
    live_open_date: str = ""  # YYYY-MM-DD (라이브 시작일)

    @property
    def display_name(self) -> str:
        """1번 위치 및 작업 표시명 규칙을 적용한 문자열을 반환합니다.

        - 라이브 시작일 확인 시: [{streamer}] {%Y-%m-%d} {title}
        - 미확인/일반 VOD: [{streamer}] {title}
        """
        if self.live_open_date:
            return f"[{self.channel_name}] {self.live_open_date} {self.video_title}"
        return f"[{self.channel_name}] {self.video_title}"


def get_ytdlp_version() -> str:
    """현재 설치된 yt-dlp 버전을 반환합니다."""
    try:
        ver_module = getattr(yt_dlp, "version", None)
        version_str = getattr(ver_module, "__version__", None) if ver_module else None
        if not version_str:
            raise YtDlpNotInstalledError("yt-dlp 버전을 확인할 수 없습니다.")
        return str(version_str)
    except YtDlpNotInstalledError:
        raise
    except Exception as err:
        raise YtDlpNotInstalledError(
            f"yt-dlp 버전을 확인할 수 없습니다: {err}"
        ) from err


_chzzk_hook_installed = False


def _ensure_chzzk_hook() -> None:
    """CHZZK 및 DASH 호환성 훅을 설정합니다.

    1. CHZZKVideoIE에서 원본 content의 liveOpenDate를 캡처합니다.
    2. Naver Neonplayer Single-file MPD DASH(sourceURL, media 누락으로 인한 KeyError)를 방지합니다.
    """
    global _chzzk_hook_installed
    if _chzzk_hook_installed:
        return
    try:
        from yt_dlp.extractor.chzzk import CHZZKVideoIE
        from yt_dlp.extractor.common import InfoExtractor

        # 1. liveOpenDate 캡처 훅
        orig_download_json = CHZZKVideoIE._download_json
        orig_real_extract = CHZZKVideoIE._real_extract

        def _hooked_download_json(self: Any, *args: Any, **kwargs: Any) -> Any:
            res = orig_download_json(self, *args, **kwargs)
            if (
                isinstance(res, dict)
                and "content" in res
                and isinstance(res["content"], dict)
            ):
                self._chzzk_live_open_date = res["content"].get("liveOpenDate")
            return res

        def _hooked_real_extract(self: Any, url: str) -> Any:
            self._chzzk_live_open_date = None
            info = orig_real_extract(self, url)
            if getattr(self, "_chzzk_live_open_date", None):
                info["live_open_date"] = self._chzzk_live_open_date
            return info

        CHZZKVideoIE._download_json = _hooked_download_json
        CHZZKVideoIE._real_extract = _hooked_real_extract

        # 2. Naver Neonplayer Single-file MPD DASH 호환 훅 (KeyError: sourceURL / media 방지)
        orig_parse_mpd_periods = InfoExtractor._parse_mpd_periods

        def _hooked_parse_mpd_periods(
            self: Any, mpd_doc: Any, *args: Any, **kwargs: Any
        ) -> Any:
            if mpd_doc is not None:
                for elem in mpd_doc.iter():
                    if (
                        elem.tag.endswith("Initialization")
                        and "sourceURL" not in elem.attrib
                    ):
                        elem.attrib["sourceURL"] = elem.attrib.get("range", "")
                    if elem.tag.endswith("SegmentURL") and "media" not in elem.attrib:
                        elem.attrib["media"] = elem.attrib.get("mediaRange", "")
            return orig_parse_mpd_periods(self, mpd_doc, *args, **kwargs)

        InfoExtractor._parse_mpd_periods = _hooked_parse_mpd_periods

        _chzzk_hook_installed = True
    except Exception:
        pass


def extract_vod_info(url: str, ydl_opts: dict[str, Any] | None = None) -> VodInfo:
    """yt-dlp를 사용하여 VOD 메타데이터를 추출합니다.

    Args:
        url: 치지직 VOD URL
        ydl_opts: 추가 yt-dlp 옵션 (쿠키 등)

    Returns:
        VodInfo: 추출된 영상 메타데이터 모델

    Raises:
        VodNotFoundError: 영상이 존재하지 않거나 삭제/비공개인 경우
        YtDlpError: 네트워크 오류 또는 yt-dlp 처리 오류 발생 시
    """
    _ensure_chzzk_hook()

    opts: dict[str, Any] = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }

    from chzzk_downloader.core.cookie_manager import (
        get_cookie_file_path,
        has_valid_cookies,
    )

    if has_valid_cookies():
        opts["cookiefile"] = str(get_cookie_file_path())

    if ydl_opts:
        opts.update(ydl_opts)

    try:
        with yt_dlp.YoutubeDL(cast(Any, opts)) as ydl:
            data = ydl.extract_info(url, download=False)
    except DownloadError as err:
        err_msg = str(err).lower()
        if (
            "404" in err_msg
            or "not found" in err_msg
            or "존재하지" in err_msg
            or "this video is unavailable" in err_msg
        ):
            raise VodNotFoundError("동영상 정보가 존재하지 않습니다.") from err
        raise YtDlpError(f"yt-dlp 영상 정보 추출 실패: {err}") from err
    except Exception as err:
        raise YtDlpError(f"yt-dlp 실행 오류: {err}") from err

    if not data:
        raise VodNotFoundError("동영상 정보를 가져올 수 없습니다.")

    formats_list: list[VodFormatInfo] = []
    raw_formats = data.get("formats")
    if isinstance(raw_formats, list):
        for fmt in raw_formats:
            if not isinstance(fmt, dict):
                continue
            format_id = str(fmt.get("format_id") or "")
            formats_list.append(
                VodFormatInfo(
                    format_id=format_id,
                    resolution=str(fmt.get("resolution") or ""),
                    width=fmt.get("width"),
                    height=fmt.get("height"),
                    fps=fmt.get("fps"),
                    tbr=fmt.get("tbr"),
                    url=str(fmt.get("url") or ""),
                )
            )

    channel_name = str(data.get("channel") or data.get("uploader") or "알 수 없음")
    video_no = str(data.get("id") or "")
    video_title = str(data.get("title") or "제목 없음")
    thumbnail_url = str(data.get("thumbnail") or "")
    duration = int(data.get("duration") or 0)

    # 라이브 시작일 (liveOpenDate 등) 추출
    live_open_date = ""
    raw_live_date = data.get("live_open_date")
    if raw_live_date and isinstance(raw_live_date, str):
        # '2024-05-06 21:00:00' -> '2024-05-06'
        live_open_date = raw_live_date.strip().split(" ")[0]
    elif data.get("was_live") or data.get("live_status") == "was_live":
        # yt-dlp upload_date fallback: '20240506' -> '2024-05-06'
        upload_date = str(data.get("upload_date") or "")
        if len(upload_date) == 8 and upload_date.isdigit():
            live_open_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"

    return VodInfo(
        video_no=video_no,
        video_title=video_title,
        channel_name=channel_name,
        thumbnail_url=thumbnail_url,
        duration=duration,
        formats=formats_list,
        live_open_date=live_open_date,
    )
