"""작업 워크트리 변경 사항을 데스크톱 폴더로 안전하게 동기화하는 자동화 스크립트."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Windows 콘솔 cp949 인코딩 방어 (UTF-8 재구성)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 소스 워크트리 루트 (scripts -> desktop-sync -> skills -> .agents -> 루트)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent

# 데스크톱 타깃 폴더
DESKTOP_TARGET = Path(r"C:\Users\이홍원\Desktop\chzzk_downloader")

# 동기화 대상 디렉터리 목록
SYNC_DIRS = [
    "src",
    "docs",
    "tools",
    ".agents/skills",
]

# 동기화 대상 루트 단일 파일 목록
SYNC_FILES = [
    "AGENTS.md",
    "pyproject.toml",
]


def sync_to_desktop() -> bool:
    print(
        f"[SYNC] 워크트리({PROJECT_ROOT}) -> 데스크톱({DESKTOP_TARGET}) 동기화 시작..."
    )

    if not DESKTOP_TARGET.exists():
        print(
            f"[WARN] 데스크톱 타깃 폴더가 존재하지 않아 자동 생성합니다: {DESKTOP_TARGET}"
        )
        DESKTOP_TARGET.mkdir(parents=True, exist_ok=True)

    success_count = 0
    for dir_rel in SYNC_DIRS:
        src_path = PROJECT_ROOT / dir_rel
        dst_path = DESKTOP_TARGET / dir_rel

        if not src_path.exists():
            print(f"[SKIP] 소스 디렉터리가 없어 건너뜁니다: {dir_rel}")
            continue

        try:
            dst_path.mkdir(parents=True, exist_ok=True)
            # 디렉터리 트리 복사 (기존 파일 덮어쓰기)
            shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
            print(f"[OK] 동기화 완료: {dir_rel} -> {dst_path}")
            success_count += 1
        except Exception as e:
            print(f"[ERR] 동기화 실패 ({dir_rel}): {e}")

    for file_rel in SYNC_FILES:
        src_file = PROJECT_ROOT / file_rel
        dst_file = DESKTOP_TARGET / file_rel

        if not src_file.exists():
            print(f"[SKIP] 소스 파일이 없어 건너뜁니다: {file_rel}")
            continue

        try:
            shutil.copy2(src_file, dst_file)
            print(f"[OK] 파일 복사 완료: {file_rel} -> {dst_file}")
            success_count += 1
        except Exception as e:
            print(f"[ERR] 파일 복사 실패 ({file_rel}): {e}")

    print(f"\n[DONE] 총 {success_count}개 항목 동기화 완료!")
    return success_count > 0


if __name__ == "__main__":
    ok = sync_to_desktop()
    sys.exit(0 if ok else 1)
