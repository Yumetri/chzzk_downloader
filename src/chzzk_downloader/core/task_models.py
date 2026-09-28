"""작업 생명주기 및 관리를 위한 핵심 데이터 모델 모듈 (RFC #87)."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class TaskStatus(Enum):
    """작업 10대 생명주기 상태 코드 (RFC #87 C00 ~ C07, C09)."""

    QUEUED = "QUEUED"  # C00: 대기 중 (창구 만석으로 대기열에서 차례를 기다림)
    ANALYZING = "ANALYZING"  # C01: URL 분석 중
    READY = "READY"  # C02: 준비 완료 (다운로드 옵션 확인 및 시작 대기)
    DOWNLOADING = "DOWNLOADING"  # C03: 다운로드/녹화 실행 중
    STOPPED = "STOPPED"  # C04: 중지됨 (재개 불가 완결 상태)
    FAILED_INVALID = "FAILED_INVALID"  # C05: 링크/URL 오류
    FAILED_LOGIN_REQUIRED = "FAILED_LOGIN_REQUIRED"  # C06: 성인인증/로그인 필요
    FAILED_DOWNLOAD = "FAILED_DOWNLOAD"  # C07: 다운로드/네트워크 실패
    COMPLETED = "COMPLETED"  # C09: 다운로드 및 검증 완료


@dataclass(frozen=True)
class TaskProgress:
    """실시간 다운로드/녹화 진행 정보 (불변 객체)."""

    task_id: str
    downloaded_bytes: int = 0
    total_bytes: int = 0
    percentage: float = 0.0  # 0.0 ~ 100.0
    speed_bytes_sec: float = 0.0  # 초당 바이트 수
    speed_str: str = ""  # 예: "15.4 MB/s"
    eta_seconds: int = 0  # 남은 시간 (초)
    eta_str: str = ""  # 예: "00:03:25"


@dataclass(frozen=True)
class TaskSpec:
    """작업 생성 및 실행 명세 (불변 객체)."""

    task_id: str
    video_url: str
    is_live: bool = False
    title: str = ""
    streamer: str = ""
    selected_quality: str = ""
    selected_ext: str = "mp4"
    save_path: Path | str = ""
