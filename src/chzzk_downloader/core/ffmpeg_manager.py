"""FFmpeg 상태 진단, 버전 파싱 및 치지직 HLS 호환성 프로빙 코어 모듈 (T0110)."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from chzzk_downloader.config import (
    DEFAULT_FFMPEG_BINARY_NAME,
    DEFAULT_FFMPEG_DOWNLOAD_URL,
    DEFAULT_FFPROBE_BINARY_NAME,
    DEFAULT_USER_AGENT,
    FFMPEG_DOWNLOAD_TIMEOUT_SEC,
    FFMPEG_PROBE_TIMEOUT_SEC,
)


class FFmpegStatus(StrEnum):
    """FFmpeg 상태 판별 열거형."""

    AVAILABLE = "사용 가능"
    NOT_FOUND = "파일 없음"
    EXECUTION_FAILED = "실행 실패"
    TIMEOUT = "응답 없음"


@dataclass
class FFmpegProbeResult:
    """FFmpeg 프로빙 및 호환성 검증 결과 데이터클래스."""

    status: FFmpegStatus
    path: Path | None = None
    version: str = ""
    supports_extension_picky: bool = False
    supports_allowed_extensions: bool = False
    compatible_args: list[str] = field(default_factory=list)
    error_message: str = ""

    @property
    def display_text(self) -> str:
        """UI 상태 라벨에 표시할 텍스트를 반환합니다."""
        if self.status == FFmpegStatus.AVAILABLE:
            ver = self.version or "unknown"
            if self.supports_extension_picky:
                return f"사용 가능 (FFmpeg {ver} · 치지직 호환)"
            return f"사용 가능 (FFmpeg {ver})"
        return self.status.value


_cached_probe_result: FFmpegProbeResult | None = None
_cached_ffprobe_probe_result: FFmpegProbeResult | None = None


def get_candidate_ffmpeg_paths() -> list[Path]:
    """우선순위 순서대로 탐색할 FFmpeg 바이너리 후보 경로 목록을 반환합니다.

    우선순위:
    1. 사용자 지정 설정 경로 (settings.json의 ffmpeg_path, 설정된 경우)
    2. PyInstaller 번들 디렉터리 (sys._MEIPASS)
    3. 시스템 임시 디렉터리 (%TEMP%/ffmpeg.exe, Hitomi 런타임 추출 경로 호환)
    4. 앱 실행/패키지 디렉터리 내 bin/ffmpeg.exe
    5. 사용자 전용 데이터 디렉터리 (~/.chzzk_downloader/bin/ffmpeg.exe)
    6. 시스템 PATH (shutil.which)
    """
    candidates: list[Path] = []

    # 1. 사용자 지정 경로
    try:
        from chzzk_downloader.core.settings_manager import get_current_settings

        settings = get_current_settings()
        if settings.ffmpeg_path:
            candidates.append(Path(settings.ffmpeg_path))
    except Exception:
        pass

    # 2. PyInstaller 번들 디렉터리
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass)
        candidates.append(p / DEFAULT_FFMPEG_BINARY_NAME)
        candidates.append(p / "bin" / DEFAULT_FFMPEG_BINARY_NAME)

    # 3. 시스템 임시 디렉터리 (%TEMP%/ffmpeg.exe)
    for env_var in ("TEMP", "TMP"):
        temp_val = os.environ.get(env_var)
        if temp_val:
            candidates.append(Path(temp_val) / DEFAULT_FFMPEG_BINARY_NAME)
            candidates.append(
                Path(temp_val) / "chzzk_downloader" / DEFAULT_FFMPEG_BINARY_NAME
            )

    # 4. 앱 내부 bin 디렉터리
    app_root = Path(__file__).resolve().parent.parent
    candidates.append(app_root / "bin" / DEFAULT_FFMPEG_BINARY_NAME)
    candidates.append(Path.cwd() / "bin" / DEFAULT_FFMPEG_BINARY_NAME)

    # 5. 사용자 전용 데이터 디렉터리
    candidates.append(
        Path.home() / ".chzzk_downloader" / "bin" / DEFAULT_FFMPEG_BINARY_NAME
    )

    # 6. 시스템 PATH
    which_path = shutil.which("ffmpeg")
    if which_path:
        candidates.append(Path(which_path))

    return candidates


def resolve_ffmpeg_path(custom_path: Path | str | None = None) -> Path | None:
    """지정된 경로 또는 후보 경로 목록에서 실제로 존재하는 첫 번째 바이너리 경로를 반환합니다."""
    if custom_path:
        try:
            p = Path(custom_path).resolve()
            if p.is_file():
                return p
        except Exception:
            return None
        return None

    for cand in get_candidate_ffmpeg_paths():
        try:
            resolved = cand.resolve()
            if resolved.is_file():
                return resolved
        except Exception:
            continue

    return None


def probe_ffmpeg(
    path: Path | str | None = None,
    timeout: float = FFMPEG_PROBE_TIMEOUT_SEC,
) -> FFmpegProbeResult:
    """지정된 또는 기본 FFmpeg 바이너리의 실행 가능 여부, 버전, 호환 인자를 검증합니다."""
    if path:
        try:
            target_path = Path(path).resolve()
        except Exception as e:
            return FFmpegProbeResult(
                status=FFmpegStatus.NOT_FOUND,
                path=None,
                error_message=f"유효하지 않은 파일 경로입니다: {e}",
            )
        if not target_path.exists() or not target_path.is_file():
            return FFmpegProbeResult(
                status=FFmpegStatus.NOT_FOUND,
                path=target_path,
                error_message=f"파일이 존재하지 않습니다: {target_path}",
            )
    else:
        resolved = resolve_ffmpeg_path()
        if not resolved:
            return FFmpegProbeResult(
                status=FFmpegStatus.NOT_FOUND,
                path=None,
                error_message="시스템 PATH 또는 번들 디렉터리에서 FFmpeg 바이너리를 찾을 수 없습니다.",
            )
        target_path = resolved

    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    # 1. 버전 파싱 및 기본 실행 테스트
    try:
        proc = subprocess.run(
            [str(target_path), "-version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        return FFmpegProbeResult(
            status=FFmpegStatus.TIMEOUT,
            path=target_path,
            error_message=f"실행 시간 초과 ({timeout}초)",
        )
    except OSError as e:
        return FFmpegProbeResult(
            status=FFmpegStatus.EXECUTION_FAILED,
            path=target_path,
            error_message=f"실행 권한 부족 또는 잘못된 실행 파일 형식: {e}",
        )
    except Exception as e:
        return FFmpegProbeResult(
            status=FFmpegStatus.EXECUTION_FAILED,
            path=target_path,
            error_message=f"예외 발생: {e}",
        )

    if proc.returncode != 0:
        return FFmpegProbeResult(
            status=FFmpegStatus.EXECUTION_FAILED,
            path=target_path,
            error_message=f"비정상 종료 코드: {proc.returncode}",
        )

    combined_output = f"{proc.stdout}\n{proc.stderr}"
    match = re.search(r"ffmpeg version\s+([^\s,]+)", combined_output)
    if not match:
        return FFmpegProbeResult(
            status=FFmpegStatus.EXECUTION_FAILED,
            path=target_path,
            error_message="FFmpeg 버전 문자열을 확인할 수 없습니다 (FFmpeg 바이너리가 아님).",
        )

    version_str = match.group(1)

    # 2. 치지직 HLS 호환 인자 프로빙 (-extension_picky 0, -allowed_extensions ALL)
    supports_picky = False
    supports_allowed = False
    try:
        help_proc = subprocess.run(
            [str(target_path), "-h", "demuxer=hls"],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
        )
        help_output = f"{help_proc.stdout}\n{help_proc.stderr}"
        supports_picky = "extension_picky" in help_output
        supports_allowed = "allowed_extensions" in help_output
    except Exception:
        pass

    compatible_args: list[str] = []
    if supports_picky:
        compatible_args.extend(["-extension_picky", "0"])
    if supports_allowed:
        compatible_args.extend(["-allowed_extensions", "ALL"])

    return FFmpegProbeResult(
        status=FFmpegStatus.AVAILABLE,
        path=target_path,
        version=version_str,
        supports_extension_picky=supports_picky,
        supports_allowed_extensions=supports_allowed,
        compatible_args=compatible_args,
    )


def get_default_ffmpeg_install_dir() -> Path:
    """자동 다운로드된 FFmpeg 바이너리를 저장할 기본 디렉터리를 반환합니다."""
    install_dir = Path.home() / ".chzzk_downloader" / "bin"
    install_dir.mkdir(parents=True, exist_ok=True)
    return install_dir


def download_ffmpeg_binary(
    target_dir: Path | str | None = None,
    download_url: str | None = None,
    timeout: float = FFMPEG_DOWNLOAD_TIMEOUT_SEC,
) -> Path | None:
    """6단계: 원격에서 FFmpeg 바이너리를 다운로드하여 로컬에 설치하고 유효성을 검증합니다."""
    global _cached_probe_result
    dest_dir = Path(target_dir) if target_dir else get_default_ffmpeg_install_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    url = download_url or DEFAULT_FFMPEG_DOWNLOAD_URL

    req = urllib.request.Request(
        url,
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except Exception:
        return None

    if not data:
        return None

    target_bin = dest_dir / DEFAULT_FFMPEG_BINARY_NAME

    # ZIP 아카이브인지 직접 바이너리인지 판별
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for member in zf.namelist():
                    norm_name = Path(member).name.lower()
                    if norm_name == DEFAULT_FFMPEG_BINARY_NAME.lower():
                        with (
                            zf.open(member) as source,
                            open(target_bin, "wb") as target,
                        ):
                            shutil.copyfileobj(source, target)
                    elif norm_name == DEFAULT_FFPROBE_BINARY_NAME.lower():
                        target_ffprobe = dest_dir / DEFAULT_FFPROBE_BINARY_NAME
                        with (
                            zf.open(member) as source,
                            open(target_ffprobe, "wb") as target,
                        ):
                            shutil.copyfileobj(source, target)
        except Exception:
            return None
    else:
        try:
            target_bin.write_bytes(data)
        except Exception:
            return None

    if not target_bin.exists():
        return None

    # 실행 권한 부여
    try:
        os.chmod(target_bin, 0o755)
    except Exception:
        pass

    probe_res = probe_ffmpeg(target_bin)
    if probe_res.status == FFmpegStatus.AVAILABLE:
        _cached_probe_result = probe_res
        return target_bin

    return None


def ensure_ffmpeg_available(
    auto_download: bool = True,
    target_dir: Path | str | None = None,
    download_url: str | None = None,
) -> tuple[bool, Path | None]:
    """1~5단계 탐색 후 부재 시 6단계 자동 다운로드를 수행하여 FFmpeg 가용성을 보장합니다.

    Returns:
        (가용 여부: bool, 가용한 바이너리 경로: Path | None)
    """
    # 1~5단계 탐색
    resolved = resolve_ffmpeg_path()
    if resolved:
        probe_res = probe_ffmpeg(resolved)
        if probe_res.status == FFmpegStatus.AVAILABLE:
            return True, resolved

    # 1~5단계 실패 시 6단계 자동 다운로드 시도
    if auto_download:
        downloaded = download_ffmpeg_binary(
            target_dir=target_dir, download_url=download_url
        )
        if downloaded:
            return True, downloaded

    return False, None


def is_ffmpeg_available(
    ffmpeg_path: Path | str | None = None,
    force_recheck: bool = False,
    auto_download: bool = False,
) -> bool:
    """FFmpeg가 사용 가능한 상태인지 확인하는 판별 가드 함수."""
    global _cached_probe_result
    if ffmpeg_path is not None:
        res = probe_ffmpeg(ffmpeg_path)
        return res.status == FFmpegStatus.AVAILABLE

    if _cached_probe_result is None or force_recheck:
        _cached_probe_result = probe_ffmpeg(None)

    if _cached_probe_result.status == FFmpegStatus.AVAILABLE:
        return True

    if auto_download:
        ok, _ = ensure_ffmpeg_available(auto_download=True)
        return ok

    return False


def get_ffmpeg_compatible_args(
    ffmpeg_path: Path | str | None = None,
) -> list[str]:
    """검증된 치지직 HLS 호환 인자 세트를 반환합니다."""
    global _cached_probe_result
    if ffmpeg_path is not None:
        res = probe_ffmpeg(ffmpeg_path)
        return res.compatible_args

    if _cached_probe_result is None:
        _cached_probe_result = probe_ffmpeg(None)

    return _cached_probe_result.compatible_args


def get_ffmpeg_path() -> Path | None:
    """현재 가용한 유효 FFmpeg 바이너리 경로를 반환합니다."""
    global _cached_probe_result
    if _cached_probe_result is None:
        _cached_probe_result = probe_ffmpeg(None)

    if _cached_probe_result.status == FFmpegStatus.AVAILABLE:
        return _cached_probe_result.path
    return None


def clear_probe_cache() -> None:
    """캐시된 프로빙 결과를 무효화합니다."""
    global _cached_probe_result, _cached_ffprobe_probe_result
    _cached_probe_result = None
    _cached_ffprobe_probe_result = None


def get_candidate_ffprobe_paths() -> list[Path]:
    """우선순위 순서대로 탐색할 FFprobe 바이너리 후보 경로 목록을 반환합니다.

    우선순위:
    1. 사용자 지정 설정 경로 (settings.json의 ffprobe_path, 설정된 경우)
    2. 해석된 FFmpeg 바이너리의 동일 디렉터리 내 ffprobe.exe
    3. PyInstaller 번들 디렉터리 (sys._MEIPASS)
    4. 시스템 임시 디렉터리 (%TEMP%/ffprobe.exe, Hitomi 런타임 추출 경로 호환)
    5. 앱 실행/패키지 디렉터리 내 bin/ffprobe.exe
    6. 사용자 전용 데이터 디렉터리 (~/.chzzk_downloader/bin/ffprobe.exe)
    7. 시스템 PATH (shutil.which)
    """
    candidates: list[Path] = []

    # 1. 사용자 지정 경로
    try:
        from chzzk_downloader.core.settings_manager import get_current_settings

        settings = get_current_settings()
        if settings.ffprobe_path:
            candidates.append(Path(settings.ffprobe_path))
    except Exception:
        pass

    # 2. FFmpeg와 동일한 폴더 내 바이너리
    try:
        ffmpeg_bin = resolve_ffmpeg_path()
        if ffmpeg_bin:
            candidates.append(ffmpeg_bin.parent / DEFAULT_FFPROBE_BINARY_NAME)
    except Exception:
        pass

    # 3. PyInstaller 번들 디렉터리
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = Path(meipass)
        candidates.append(p / DEFAULT_FFPROBE_BINARY_NAME)
        candidates.append(p / "bin" / DEFAULT_FFPROBE_BINARY_NAME)

    # 4. 시스템 임시 디렉터리 (%TEMP%/ffprobe.exe)
    for env_var in ("TEMP", "TMP"):
        temp_val = os.environ.get(env_var)
        if temp_val:
            candidates.append(Path(temp_val) / DEFAULT_FFPROBE_BINARY_NAME)
            candidates.append(
                Path(temp_val) / "chzzk_downloader" / DEFAULT_FFPROBE_BINARY_NAME
            )

    # 5. 앱 내부 bin 디렉터리
    app_root = Path(__file__).resolve().parent.parent
    candidates.append(app_root / "bin" / DEFAULT_FFPROBE_BINARY_NAME)
    candidates.append(Path.cwd() / "bin" / DEFAULT_FFPROBE_BINARY_NAME)

    # 6. 사용자 전용 데이터 디렉터리
    candidates.append(
        Path.home() / ".chzzk_downloader" / "bin" / DEFAULT_FFPROBE_BINARY_NAME
    )

    # 7. 시스템 PATH
    which_path = shutil.which("ffprobe")
    if which_path:
        candidates.append(Path(which_path))

    return candidates


def resolve_ffprobe_path(custom_path: Path | str | None = None) -> Path | None:
    """지정된 경로 또는 후보 경로 목록에서 실제로 존재하는 첫 번째 FFprobe 바이너리 경로를 반환합니다."""
    if custom_path:
        try:
            p = Path(custom_path).resolve()
            if p.is_file():
                return p
        except Exception:
            return None
        return None

    for cand in get_candidate_ffprobe_paths():
        try:
            resolved = cand.resolve()
            if resolved.is_file():
                return resolved
        except Exception:
            continue

    return None


def probe_ffprobe(
    path: Path | str | None = None,
    timeout: float = FFMPEG_PROBE_TIMEOUT_SEC,
) -> FFmpegProbeResult:
    """지정된 또는 기본 FFprobe 바이너리의 실행 가능 여부와 버전을 검증합니다."""
    if path:
        try:
            target_path = Path(path).resolve()
        except Exception as e:
            return FFmpegProbeResult(
                status=FFmpegStatus.NOT_FOUND,
                path=None,
                error_message=f"유효하지 않은 파일 경로입니다: {e}",
            )
        if not target_path.exists() or not target_path.is_file():
            return FFmpegProbeResult(
                status=FFmpegStatus.NOT_FOUND,
                path=target_path,
                error_message=f"파일이 존재하지 않습니다: {target_path}",
            )
    else:
        resolved = resolve_ffprobe_path()
        if not resolved:
            return FFmpegProbeResult(
                status=FFmpegStatus.NOT_FOUND,
                path=None,
                error_message="시스템 PATH 또는 번들 디렉터리에서 FFprobe 바이너리를 찾을 수 없습니다.",
            )
        target_path = resolved

    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    try:
        proc = subprocess.run(
            [str(target_path), "-version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        return FFmpegProbeResult(
            status=FFmpegStatus.TIMEOUT,
            path=target_path,
            error_message=f"실행 시간 초과 ({timeout}초)",
        )
    except OSError as e:
        return FFmpegProbeResult(
            status=FFmpegStatus.EXECUTION_FAILED,
            path=target_path,
            error_message=f"실행 권한 부족 또는 잘못된 실행 파일 형식: {e}",
        )
    except Exception as e:
        return FFmpegProbeResult(
            status=FFmpegStatus.EXECUTION_FAILED,
            path=target_path,
            error_message=f"예외 발생: {e}",
        )

    if proc.returncode != 0:
        return FFmpegProbeResult(
            status=FFmpegStatus.EXECUTION_FAILED,
            path=target_path,
            error_message=f"비정상 종료 코드: {proc.returncode}",
        )

    combined_output = f"{proc.stdout}\n{proc.stderr}"
    match = re.search(r"ffprobe version\s+([^\s,]+)", combined_output)
    if not match:
        return FFmpegProbeResult(
            status=FFmpegStatus.EXECUTION_FAILED,
            path=target_path,
            error_message="FFprobe 버전 문자열을 확인할 수 없습니다 (FFprobe 바이너리가 아님).",
        )

    version_str = match.group(1)
    return FFmpegProbeResult(
        status=FFmpegStatus.AVAILABLE,
        path=target_path,
        version=version_str,
    )


def is_ffprobe_available(
    ffprobe_path: Path | str | None = None,
    force_recheck: bool = False,
) -> bool:
    """FFprobe가 사용 가능한 상태인지 확인하는 판별 가드 함수."""
    global _cached_ffprobe_probe_result
    if ffprobe_path is not None:
        res = probe_ffprobe(ffprobe_path)
        return res.status == FFmpegStatus.AVAILABLE

    if _cached_ffprobe_probe_result is None or force_recheck:
        _cached_ffprobe_probe_result = probe_ffprobe(None)

    return _cached_ffprobe_probe_result.status == FFmpegStatus.AVAILABLE


def get_ffprobe_path() -> Path | None:
    """현재 가용한 유효 FFprobe 바이너리 경로를 반환합니다."""
    global _cached_ffprobe_probe_result
    if _cached_ffprobe_probe_result is None:
        _cached_ffprobe_probe_result = probe_ffprobe(None)

    if _cached_ffprobe_probe_result.status == FFmpegStatus.AVAILABLE:
        return _cached_ffprobe_probe_result.path
    return None


def probe_media_file(
    file_path: Path | str,
    timeout: float = 10.0,
) -> dict[str, Any] | None:
    """FFprobe를 호출하여 미디어 파일의 스트림 정보 및 포맷 메타데이터를 JSON으로 파싱합니다."""
    ffprobe_bin = get_ffprobe_path()
    if not ffprobe_bin:
        return None

    path_obj = Path(file_path).resolve()
    if not path_obj.exists() or not path_obj.is_file():
        return None

    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    cmd = [
        str(ffprobe_bin),
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path_obj),
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
        )
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout)
    except Exception:
        return None


def verify_media_file_integrity(
    file_path: Path | str,
    timeout: float = 10.0,
) -> tuple[bool, str]:
    """미디어 파일의 존재 유무, 용량, 스트림 유효성 및 무결성을 진단합니다.

    Returns:
        (성공 여부: bool, 결과 메시지 또는 원인: str)
    """
    path_obj = Path(file_path).resolve()
    if not path_obj.exists():
        return False, f"파일이 존재하지 않습니다: {path_obj.name}"

    try:
        if path_obj.stat().st_size == 0:
            return False, "파일 크기가 0바이트입니다 (비어 있음)."
    except OSError as e:
        return False, f"파일 상태 확인 실패: {e}"

    info = probe_media_file(path_obj, timeout=timeout)
    if info is None:
        if not is_ffprobe_available():
            return (
                True,
                "FFprobe가 없어 정밀 스트림 검증을 건너뛰었습니다 (파일 크기 정상).",
            )
        return (
            False,
            "FFprobe 미디어 분석에 실패했습니다 (손상된 파일 또는 미인식 포맷).",
        )

    streams = info.get("streams", [])
    if not streams:
        return False, "유효한 비디오/오디오 스트림을 찾을 수 없습니다."

    has_video = any(s.get("codec_type") == "video" for s in streams)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    if not has_video and not has_audio:
        return False, "스트림에 비디오 또는 오디오 트랙이 포함되어 있지 않습니다."

    return (
        True,
        f"검증 완료 (스트림 {len(streams)}개: 비디오={has_video}, 오디오={has_audio})",
    )
    return (
        True,
        f"검증 완료 (스트림 {len(streams)}개: 비디오={has_video}, 오디오={has_audio})",
    )
