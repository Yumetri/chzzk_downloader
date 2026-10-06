"""오류 분류 단일화 모듈 (D04).

문자열 부분매칭 중복을 제거하고 HTTP 상태 코드 및 정밀 키워드 기반으로
작업 실패 상태(TaskStatus)를 단일 지점에서 결정합니다.
"""

from __future__ import annotations

import re

from chzzk_downloader.core.task_models import TaskStatus

_HTTP_STATUS_PATTERN = re.compile(
    r"(?:HTTP\s*(?:Error)?|HTTPError)\s*:?\s*(\d{3})(?!\d)", re.IGNORECASE
)

_LOGIN_KEYWORDS = (
    "login",
    "로그인",
    "성인",
    "adult",
    "19+",
    "19세",
    "19금",
    "연령 제한",
    "연령제한",
    "본인 인증",
    "본인인증",
    "청소년 관람불가",
    "unauthorized",
    "forbidden",
)

_INVALID_KEYWORDS = (
    "vodnotfound",
    "not found",
    "notfound",
    "비공개",
    "존재하지 않",
    "삭제된",
    "invalid url",
    "잘못된 url",
    "유효하지 않",
)


def _classify_http_status(status_code: int | None, msg: str) -> TaskStatus | None:
    """HTTP 상태 코드 또는 메시지 내 HTTP 에러 코드를 분석하여 상태를 반환합니다."""
    code = status_code
    if code is None and msg:
        match = _HTTP_STATUS_PATTERN.search(msg)
        if match:
            code = int(match.group(1))

    if code is not None:
        if code in (401, 403):
            return TaskStatus.FAILED_LOGIN_REQUIRED
        if code in (404, 410):
            return TaskStatus.FAILED_INVALID
        if 500 <= code < 600:
            return TaskStatus.FAILED_DOWNLOAD
    return None


def classify_error(
    exc_type: str = "",
    msg: str = "",
    http_status: int | None = None,
) -> TaskStatus:
    """오류 유형, 메시지, HTTP 상태코드를 기반으로 TaskStatus 실패 상태를 단일 분류합니다."""
    # 1. HTTP 상태 코드 우선 분류
    http_result = _classify_http_status(http_status, msg)
    if http_result is not None:
        return http_result

    combined = f"{exc_type} {msg}".lower()

    # 2. 미디어/인코딩 데이터 손상 특수 패턴 (URL 유효성과 무관한 다운로드 오류)
    if "invalid data found" in combined:
        return TaskStatus.FAILED_DOWNLOAD

    # 3. 로그인 및 성인/연령 인증 필요
    if any(k in combined for k in _LOGIN_KEYWORDS):
        return TaskStatus.FAILED_LOGIN_REQUIRED

    # 4. 유효하지 않은 / 비공개 / 삭제된 URL
    if any(k in combined for k in _INVALID_KEYWORDS):
        return TaskStatus.FAILED_INVALID

    # 5. 기본 다운로드 실패 (로컬 경로 OSError 등 미분류 시스템 오류 포함)
    return TaskStatus.FAILED_DOWNLOAD
