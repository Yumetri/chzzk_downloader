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


def generate_vod_filename(vod_info: VodInfo, ext: str = ".mp4") -> str:
    """VOD 정보와 확장자를 바탕으로 표준 저장 파일명을 생성합니다.

    명명 규칙:
      - 라이브일시 확인 시: [{streamer}] date:{liveOpenDate}; {title} ({videoNo}){ext}
      - 일반 VOD: [{streamer}] {title} ({videoNo}){ext}
      - 콜론은 전각 콜론(：)으로 변환
    """
    if not ext.startswith("."):
        ext = f".{ext}"

    streamer = vod_info.channel_name or "알 수 없는 스트리머"
    title = vod_info.video_title or "제목 없음"
    video_no = vod_info.video_no or "0"

    if vod_info.live_open_date:
        raw_name = f"[{streamer}] date:{vod_info.live_open_date}; {title} ({video_no})"
    else:
        raw_name = f"[{streamer}] {title} ({video_no})"

    sanitized_stem = sanitize_filename(raw_name)
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
