"""작업 생명주기 및 관리를 위한 핵심 데이터 모델 모듈 (RFC #87)."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class TaskStatus(Enum):
    """작업 9대 생명주기 상태 코드 (RFC #87 C01 ~ C09)."""

    QUEUED = "QUEUED"  # C09: 대기 중 (창구 만석으로 대기열에서 차례를 기다림)
    ANALYZING = "ANALYZING"  # C01: URL 분석 중
    READY = "READY"  # C02: 준비 완료 (다운로드 옵션 확인 및 시작 대기)
    DOWNLOADING = "DOWNLOADING"  # C03: 다운로드/녹화 실행 중
    STOPPED = "STOPPED"  # C04: 중지됨 (재개 불가 완결 상태)
    FAILED_INVALID = "FAILED_INVALID"  # C05: 링크/URL 오류
    FAILED_LOGIN_REQUIRED = "FAILED_LOGIN_REQUIRED"  # C06: 성인인증/로그인 필요
    FAILED_DOWNLOAD = "FAILED_DOWNLOAD"  # C07: 다운로드/네트워크 실패
    COMPLETED = "COMPLETED"  # C08: 다운로드 및 검증 완료


def format_byte_size(size_bytes: int | float) -> str:
    """바이트 크기를 사람이 읽기 쉬운 B, KB, MB, GB 단위로 포맷팅합니다."""
    if size_bytes <= 0:
        return "0.0 B"
    num = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(num)} B"
            elif unit in ("GB", "TB"):
                return f"{num:.2f} {unit}"
            else:
                return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} B"


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
    elapsed_seconds: float = 0.0  # 경과 시간 (초)

    @property
    def elapsed_str(self) -> str:
        """경과 시간을 'HH:MM:SS' 형식 문자열로 반환합니다."""
        secs = int(max(0.0, self.elapsed_seconds))
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    @property
    def downloaded_size_str(self) -> str:
        """다운로드된 용량을 포맷팅된 문자열로 반환합니다."""
        return format_byte_size(self.downloaded_bytes)

    @property
    def total_size_str(self) -> str:
        """전체 용량을 포맷팅된 문자열로 반환합니다. (알 수 없는 경우 '--')"""
        if self.total_bytes <= 0:
            return "--"
        return format_byte_size(self.total_bytes)

    @property
    def detailed_percentage_str(self) -> str:
        """소수점 1자리 퍼센트 문자열을 반환합니다."""
        import math

        if math.isnan(self.percentage) or math.isinf(self.percentage):
            return "0.0%"
        return f"{self.percentage:.1f}%"

    @property
    def progress_summary(self) -> str:
        """호버 툴팁용 요약 문자열 (예: '11.2% (137.8 MB / 1.20 GB)')을 반환합니다."""
        if self.total_bytes > 0:
            return (
                f"{self.detailed_percentage_str} "
                f"({self.downloaded_size_str} / {self.total_size_str})"
            )
        return f"{self.detailed_percentage_str} ({self.downloaded_size_str})"


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
