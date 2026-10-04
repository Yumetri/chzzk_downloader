"""VOD 구간 다운로드를 위한 타임스탬프 파싱 및 구간 검증 순수 도메인 모듈 (T0601)."""

from __future__ import annotations

import math


def _parse_part(token: str) -> float:
    """단일 시간 토큰 문자열을 양수 유한 실수로 파싱합니다."""
    trimmed = token.strip()
    if trimmed.startswith("-"):
        raise ValueError("타임스탬프는 음수일 수 없습니다.")
    val = float(trimmed)
    if math.isnan(val) or math.isinf(val):
        raise ValueError("유효하지 않은 숫자 타임스탬프입니다.")
    return val


def _parse_colon_time(parts: list[str], raw: str) -> float:
    """콜론으로 구분된 시간 문자열(MM:SS 또는 HH:MM:SS)을 초 단위 부동소수점으로 파싱합니다."""
    if len(parts) == 2:
        m = _parse_part(parts[0])
        sec = _parse_part(parts[1])
        if sec >= 60.0:
            raise ValueError(f"초 단위는 60 미만이어야 합니다: {sec}")
        return m * 60.0 + sec

    # len(parts) == 3: HH:MM:SS
    h = _parse_part(parts[0])
    m = _parse_part(parts[1])
    sec = _parse_part(parts[2])
    if m >= 60.0 or sec >= 60.0:
        raise ValueError("분/초 단위는 60 미만이어야 합니다.")
    return h * 3600.0 + m * 60.0 + sec


def parse_timestamp(val: str | int | float) -> float:
    """문자열 또는 숫자 형태의 타임스탬프를 초 단위 부동소수점으로 파싱합니다.

    지원 형식:
        - 초 단위 정수/실수: 120, 120.5, "120", "120.5"
        - 'SS' 또는 'SS.ss': "45", "45.25"
        - 'M:SS' 또는 'MM:SS': "1:30", "01:30", "1:30.5"
        - 'H:MM:SS' 또는 'HH:MM:SS': "1:00:00", "01:23:45", "01:23:45.50"

    Raises:
        ValueError: 음수이거나 형식이 잘못된 경우
    """
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            raise ValueError("유효하지 않은 숫자 타임스탬프입니다.")
        if val < 0:
            raise ValueError("타임스탬프는 음수일 수 없습니다.")
        return float(val)

    s = str(val).strip()
    if not s:
        raise ValueError("타임스탬프가 비어있습니다.")

    parts = s.split(":")
    if len(parts) > 3:
        raise ValueError(f"콜론이 너무 많습니다: {s}")

    try:
        if len(parts) == 1:
            sec = _parse_part(parts[0])
            return sec

        return _parse_colon_time(parts, s)
    except ValueError as e:
        if "타임스탬프" in str(e) or "미만" in str(e) or "유효하지 않은" in str(e):
            raise
        raise ValueError(f"타임스탬프 파싱 실패: {s}") from e


def validate_section(
    start: float | str | None,
    end: float | str | None,
    duration: float | None = None,
) -> tuple[float, float]:
    """구간 다운로드의 시작 및 종료 시각을 파싱하고 유효성을 엄격하게 검증합니다.

    규칙:
        - 0 <= start < end <= duration (duration이 양수인 경우)

    Returns:
        tuple[float, float]: (시작_초, 종료_초)

    Raises:
        ValueError: 구간이 유효하지 않은 경우
    """
    start_sec = parse_timestamp(start) if start is not None else 0.0

    if end is not None:
        end_sec = parse_timestamp(end)
    elif duration is not None and duration > 0:
        end_sec = float(duration)
    else:
        raise ValueError("종료 시각 또는 영상 전체 길이가 제공되어야 합니다.")

    if start_sec < 0:
        raise ValueError(f"시작 시각은 음수일 수 없습니다: {start_sec}")

    if start_sec >= end_sec:
        raise ValueError(
            f"시작 시각은 종료 시각보다 빨라야 합니다: {start_sec} >= {end_sec}"
        )

    if duration is not None and duration > 0 and end_sec > (duration + 1e-4):
        raise ValueError(
            f"종료 시각이 전체 영상 길이를 초과할 수 없습니다: {end_sec} > {duration}"
        )

    return (start_sec, end_sec)


def format_timestamp(seconds: float, use_fraction: bool = False) -> str:
    """초 단위 시간을 'HH:MM:SS' 또는 'HH:MM:SS.ss' 문자열로 포맷팅합니다."""
    secs = max(0.0, float(seconds))
    if use_fraction:
        total_cs = int(round(secs * 100))
        cs = total_cs % 100
        total_int_secs = total_cs // 100
        h = total_int_secs // 3600
        m = (total_int_secs % 3600) // 60
        s = total_int_secs % 60
        return f"{h:02d}:{m:02d}:{s:02d}.{cs:02d}"

    total_int_secs = int(secs)
    h = total_int_secs // 3600
    m = (total_int_secs % 3600) // 60
    s = total_int_secs % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_section_suffix(start: float, end: float | None = None) -> str:
    """파일명에 부착할 구간 접미사(예: '[00_10_00-00_25_30]')를 생성합니다."""

    def _to_file_time(sec: float) -> str:
        s_int = int(max(0.0, round(sec)))
        h = s_int // 3600
        m = (s_int % 3600) // 60
        s = s_int % 60
        return f"{h:02d}_{m:02d}_{s:02d}"

    if end is None or end <= start:
        return f"[{_to_file_time(start)}-end]"

    return f"[{_to_file_time(start)}-{_to_file_time(end)}]"
