"""VOD 파일명 생성 및 중복 파일명 해결 모듈 (T0109)."""

import re
from pathlib import Path

from chzzk_downloader.core.ytdlp import VodInfo

# 파일시스템 금지 문자를 보존성이 높은 전각(Fullwidth) 유니코드 문자로 치환하는 매핑 (Hitomi 표준)
FULLWIDTH_CHAR_MAP: dict[str, str] = {
    ":": "\uff1a",  # 전각 콜론 (：)
    "/": "\uff0f",  # 전각 슬래시 (／)
    "?": "\uff1f",  # 전각 물음표 (？)
    "*": "\uff0a",  # 전각 별표 (＊)
    "\\": "\uff3c",  # 전각 역슬래시 (＼)
    "|": "\uff5c",  # 전각 수직선 (｜)
    '"': "\uff02",  # 전각 따옴표 (＂)
    "<": "\uff1c",  # 전각 부등호 (＜)
    ">": "\uff1e",  # 전각 부등호 (＞)
}

# 제어 문자 및 기타 파일시스템 금지 문자 정규식
_CONTROL_CHARS_REGEX = re.compile(r"[\r\n\t\x00-\x1f\x7f]")


def sanitize_filename(name: str) -> str:
    """파일명에서 파일시스템 금지 문자를 의미를 보존하는 전각(Fullwidth) 문자로 치환합니다."""
    # 1. 파일시스템 금지 문자를 전각 유니코드 문자로 치환 (:, /, ?, *, \, |, ", <, >)
    sanitized = name
    for ch, full_ch in FULLWIDTH_CHAR_MAP.items():
        sanitized = sanitized.replace(ch, full_ch)

    # 2. 제어 문자(\r, \n, \t 등) 공백 치환
    sanitized = _CONTROL_CHARS_REGEX.sub(" ", sanitized)

    # 3. 연속 공백 정리 및 앞뒤 공백/마침표 제거
    sanitized = re.sub(r"\s+", " ", sanitized).strip(" .")
    return sanitized or "untitled"


MAX_STEM_LENGTH = 200


def adjust_live_open_date(live_open_date: str, offset_seconds: float | None) -> str:
    """라이브 시작일시에 구간 시작 시간(offset_seconds)을 가산하여 보정된 일시를 반환합니다.

    Args:
        live_open_date: 'YYYY-MM-DD HH:MM:SS', 'YYYY-MM-DD HH:MM', 'YYYY-MM-DD' 형식의 문자열
        offset_seconds: 가산할 초 단위 실수/정수 (0.0 이하이거나 None이면 원본 반환)
    """
    if not live_open_date or not offset_seconds or offset_seconds <= 0:
        return live_open_date

    from datetime import datetime, timedelta

    cleaned = live_open_date.strip()
    dt: datetime | None = None
    has_seconds = False

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(cleaned, fmt)
            has_seconds = fmt == "%Y-%m-%d %H:%M:%S"
            break
        except ValueError:
            pass

    if dt is None:
        return live_open_date

    offset_delta = timedelta(seconds=int(round(offset_seconds)))
    new_dt = dt + offset_delta

    add_sec = int(round(offset_seconds)) % 60 != 0
    if has_seconds or add_sec:
        return new_dt.strftime("%Y-%m-%d %H:%M:%S")
    return new_dt.strftime("%Y-%m-%d %H:%M")


def _build_prefix_and_suffix(
    vod_info: VodInfo,
    section_start: float | None = None,
    section_end: float | None = None,
) -> tuple[str, str, str, str]:
    """파일명 구성을 위한 (prefix, suffix, sanitized_streamer, sanitized_date) 튜플을 반환합니다."""
    streamer = vod_info.channel_name or "알 수 없는 스트리머"
    video_no = vod_info.video_no or "0"

    sanitized_streamer = sanitize_filename(streamer)
    sanitized_video_no = sanitize_filename(video_no)

    sanitized_date = ""
    if vod_info.live_open_date:
        effective_date = adjust_live_open_date(vod_info.live_open_date, section_start)
        sanitized_date = sanitize_filename(effective_date)
        prefix = f"[{sanitized_streamer}] {sanitized_date} "
    else:
        prefix = f"[{sanitized_streamer}] "

    suffix = f" ({sanitized_video_no})"
    if section_start is not None or section_end is not None:
        from chzzk_downloader.core.section_parser import format_section_suffix

        s_start = section_start if section_start is not None else 0.0
        s_end = section_end
        if (
            s_end is None
            and vod_info.duration > 0
            and float(vod_info.duration) > s_start
        ):
            s_end = float(vod_info.duration)
        suffix = f"{suffix} {format_section_suffix(s_start, s_end)}"

    return prefix, suffix, sanitized_streamer, sanitized_date


def generate_vod_filename(
    vod_info: VodInfo,
    ext: str = ".mp4",
    section_start: float | None = None,
    section_end: float | None = None,
) -> str:
    """VOD 정보와 확장자를 바탕으로 표준 저장 파일명을 생성합니다.

    명명 규칙:
      - 라이브일시 확인 시: [{streamer}] {liveOpenDateTime} {title} ({videoNo}){ext}
      - 일반 VOD: [{streamer}] {title} ({videoNo}){ext}
      - 구간 다운로드 시: ... ({videoNo}) [{시작}-{종료}]{ext}
      - 콜론은 전각 콜론(：)으로 변환
      - stem 길이가 200자를 초과할 경우 핵심 메타데이터(스트리머, 날짜, 번호, 구간)를 보존하고 제목을 안전하게 절단(...)
    """
    if not ext.startswith("."):
        ext = f".{ext}"

    prefix, suffix, sanitized_streamer, sanitized_date = _build_prefix_and_suffix(
        vod_info, section_start, section_end
    )
    title = vod_info.video_title or "제목 없음"

    sanitized_title = sanitize_filename(title)
    fixed_len = len(prefix) + len(suffix)

    if fixed_len + len(sanitized_title) > MAX_STEM_LENGTH:
        avail_title_len = max(0, MAX_STEM_LENGTH - fixed_len - 3)  # 3은 "..." 말줄임표
        if avail_title_len > 0:
            truncated_title = sanitized_title[:avail_title_len].rstrip(" .") + "..."
            sanitized_stem = f"{prefix}{truncated_title}{suffix}"
        else:
            # 접두사+접미사 자체가 197자 이상인 경우 스트리머 이름을 슬라이싱하여 200자 제한 엄격 준수
            overflow = fixed_len - MAX_STEM_LENGTH + 3
            trimmed_streamer = sanitized_streamer[:-overflow].rstrip(" .") + "..."
            if vod_info.live_open_date:
                sanitized_stem = (
                    f"[{trimmed_streamer}] {sanitized_date} {suffix.lstrip()}"
                )
            else:
                sanitized_stem = f"[{trimmed_streamer}]{suffix}"
    else:
        sanitized_stem = f"{prefix}{sanitized_title}{suffix}"

    # 최종 안전 가드: 200자 초과 방어 및 파일시스템 금지 문자 최종 단일 관문화
    sanitized_stem = sanitize_filename(sanitized_stem)
    if len(sanitized_stem) > MAX_STEM_LENGTH:
        # 접미사(VOD 번호)는 가급적 보존
        if len(suffix) < MAX_STEM_LENGTH - 10:
            head_len = MAX_STEM_LENGTH - len(suffix) - 3
            sanitized_stem = sanitized_stem[:head_len].rstrip(" .") + "..." + suffix
        else:
            sanitized_stem = sanitized_stem[: MAX_STEM_LENGTH - 3] + "..."

    return f"{sanitized_stem}{ext}"


def resolve_duplicate_filename(dir_or_path: Path, filename: str | None = None) -> Path:
    """지정된 파일 또는 디렉터리에 동일한 파일이 존재할 경우 `(1)`, `(2)` 넘버링을 적용한 새 경로를 반환합니다."""
    if filename is not None:
        target_path = dir_or_path / filename
    else:
        target_path = dir_or_path

    if not target_path.exists():
        return target_path

    parent_dir = target_path.parent
    stem = target_path.stem
    suffix = target_path.suffix

    counter = 1
    while True:
        candidate = parent_dir / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
