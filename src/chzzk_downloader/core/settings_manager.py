"""애플리케이션 기본 다운로드 설정 관리 모듈 (T0108)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from chzzk_downloader.config import (
    AVAILABLE_EXTENSIONS,
    AVAILABLE_QUALITIES,
    DEFAULT_DOWNLOAD_DIR_NAME,
    DEFAULT_SETTINGS_FILE_PATH,
)


@dataclass
class AppSettings:
    """애플리케이션 전역 설정 데이터클래스."""

    download_dir: Path
    default_quality: str = "최고 화질"
    file_extension: str = ".mp4"
    vod_auto_download: bool = True

    def to_dict(self) -> dict[str, Any]:
        """JSON 직렬화를 위한 딕셔너리로 변환합니다."""
        return {
            "download_dir": str(self.download_dir),
            "default_quality": self.default_quality,
            "file_extension": self.file_extension,
            "vod_auto_download": self.vod_auto_download,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        """딕셔너리로부터 AppSettings 인스턴스를 생성합니다."""
        d_dir = Path(data.get("download_dir", get_default_download_dir()))
        quality = data.get("default_quality", "최고 화질")
        if quality not in AVAILABLE_QUALITIES:
            quality = "최고 화질"
        ext = data.get("file_extension", ".mp4")
        if ext not in AVAILABLE_EXTENSIONS:
            ext = ".mp4"
        auto_dl = bool(data.get("vod_auto_download", True))
        return cls(
            download_dir=d_dir,
            default_quality=quality,
            file_extension=ext,
            vod_auto_download=auto_dl,
        )


_custom_settings_path: Path | None = None
_current_settings: AppSettings | None = None


def set_custom_settings_path(path: Path | None) -> None:
    """테스트 또는 격리 환경용 사용자 정의 설정 파일 경로를 지정합니다."""
    global _custom_settings_path, _current_settings
    _custom_settings_path = path
    _current_settings = None


def get_settings_file_path() -> Path:
    """현재 설정 파일 경로를 반환합니다."""
    return _custom_settings_path or DEFAULT_SETTINGS_FILE_PATH


def get_default_download_dir() -> Path:
    """애플리케이션 실행/GUI가 속한 폴더 하위 기본 다운로드 디렉터리 경로를 반환하고 생성합니다."""
    default_dir = Path.cwd() / DEFAULT_DOWNLOAD_DIR_NAME
    try:
        default_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # 작업 디렉터리에 생성 실패 시 사용자 홈 하위로 폴백
        fallback_dir = Path.home() / "Downloads" / DEFAULT_DOWNLOAD_DIR_NAME
        fallback_dir.mkdir(parents=True, exist_ok=True)
        return fallback_dir
    return default_dir


def validate_download_dir(path: Path | str) -> tuple[bool, str]:
    """저장 폴더가 실제로 존재하고 쓰기 가능한지 실질적인 파일 생성/삭제 테스트를 통해 검증합니다.

    Returns:
        (is_valid, error_message)
    """
    try:
        target = Path(path).resolve()
    except Exception as e:
        return False, f"유효하지 않은 경로입니다: {e}"

    if not target.exists():
        return False, f"폴더가 존재하지 않습니다: {target}"
    if not target.is_dir():
        return False, f"지정된 경로가 폴더가 아닙니다: {target}"

    test_file = target / f".write_test_{uuid4().hex}.tmp"
    try:
        test_file.write_text("write_test", encoding="utf-8")
    except Exception as e:
        return False, f"폴더 쓰기 권한이 없습니다: {e}"
    finally:
        if test_file.exists():
            try:
                test_file.unlink()
            except OSError:
                pass

    return True, ""


def load_settings(settings_path: Path | None = None) -> AppSettings:
    """설정 파일에서 애플리케이션 설정을 로드합니다. 파일이 없거나 손상된 경우 기본값으로 복구 및 저장합니다."""
    global _current_settings
    target_path = settings_path or get_settings_file_path()

    if not target_path.is_file():
        default_settings = AppSettings(download_dir=get_default_download_dir())
        save_settings(default_settings, target_path)
        _current_settings = default_settings
        return default_settings

    try:
        raw_text = target_path.read_text(encoding="utf-8").strip()
        if not raw_text:
            raise ValueError("설정 파일이 비어 있습니다.")
        data = json.loads(raw_text)
        if not isinstance(data, dict):
            raise TypeError("설정 데이터는 JSON 객체여야 합니다.")
    except Exception:
        # 손상된 설정 파일 복구
        default_settings = AppSettings(download_dir=get_default_download_dir())
        save_settings(default_settings, target_path)
        _current_settings = default_settings
        return default_settings

    settings = AppSettings.from_dict(data)

    # 폴더 유효성 검증 및 비정상 시 기본 디렉터리로 복구
    is_valid, _ = validate_download_dir(settings.download_dir)
    if not is_valid:
        settings.download_dir = get_default_download_dir()
        save_settings(settings, target_path)

    _current_settings = settings
    return settings


def save_settings(settings: AppSettings, settings_path: Path | None = None) -> bool:
    """애플리케이션 설정을 임시 파일 경유 원자적(Atomic) 교체로 영속화하여 비정상 종료 시 손상을 방지합니다."""
    global _current_settings
    target_path = settings_path or get_settings_file_path()
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            target_path.parent.chmod(0o700)
        except OSError:
            pass

        content = json.dumps(settings.to_dict(), indent=2, ensure_ascii=False)
        # 원자적 파일 교체 (Atomic Write)
        tmp_path = target_path.with_name(f"{target_path.name}.{uuid4().hex}.tmp")
        try:
            tmp_path.write_text(content, encoding="utf-8")
            try:
                tmp_path.chmod(0o600)
            except OSError:
                pass
            tmp_path.replace(target_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

        _current_settings = settings
        return True
    except Exception:
        return False


def get_current_settings() -> AppSettings:
    """현재 메모리에 로드된 전역 설정을 반환합니다."""
    global _current_settings
    if _current_settings is None:
        _current_settings = load_settings()
    return _current_settings


def update_current_settings(
    *,
    download_dir: Path | str | None = None,
    default_quality: str | None = None,
    file_extension: str | None = None,
    vod_auto_download: bool | None = None,
) -> tuple[bool, str]:
    """현재 전역 설정을 갱신하고 영속화합니다."""
    current = get_current_settings()

    new_dir = current.download_dir
    if download_dir is not None:
        valid, err = validate_download_dir(download_dir)
        if not valid:
            return False, err
        new_dir = Path(download_dir).resolve()

    new_quality = current.default_quality
    if default_quality is not None:
        if default_quality not in AVAILABLE_QUALITIES:
            return False, f"지원하지 않는 화질입니다: {default_quality}"
        new_quality = default_quality

    new_ext = current.file_extension
    if file_extension is not None:
        if file_extension not in AVAILABLE_EXTENSIONS:
            return False, f"지원하지 않는 파일 확장자입니다: {file_extension}"
        new_ext = file_extension

    new_auto = (
        current.vod_auto_download
        if vod_auto_download is None
        else bool(vod_auto_download)
    )

    updated = AppSettings(
        download_dir=new_dir,
        default_quality=new_quality,
        file_extension=new_ext,
        vod_auto_download=new_auto,
    )
    if save_settings(updated):
        return True, "설정이 성공적으로 저장되었습니다."
    return False, "설정 저장에 실패했습니다."
