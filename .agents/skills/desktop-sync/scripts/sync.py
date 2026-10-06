"""작업 워크트리 변경 사항을 데스크톱 폴더로 안전하게 동기화하고, 규칙 및 문서의 양방향 업데이트를 지원하는 자동화 스크립트."""

from __future__ import annotations

import argparse
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

# 동기화 대상 개별 파일 목록 (규칙 및 설정)
SYNC_FILES = [
    "AGENTS.md",
]


def sync_codebase(from_desktop: bool = False) -> bool:
    src_base = DESKTOP_TARGET if from_desktop else PROJECT_ROOT
    dst_base = PROJECT_ROOT if from_desktop else DESKTOP_TARGET
    direction = "데스크톱 -> 워크스페이스" if from_desktop else "워크스페이스 -> 데스크톱"

    print(f"[SYNC] {direction} 동기화 시작... ({src_base} -> {dst_base})")

    if not dst_base.exists():
        print(f"[WARN] 타깃 폴더가 존재하지 않아 자동 생성합니다: {dst_base}")
        dst_base.mkdir(parents=True, exist_ok=True)

    success_count = 0

    # 1. 디렉터리 동기화
    for dir_rel in SYNC_DIRS:
        src_path = src_base / dir_rel
        dst_path = dst_base / dir_rel

        if not src_path.exists():
            print(f"[SKIP] 소스 디렉터리가 없어 건너뜁니다: {dir_rel}")
            continue

        try:
            dst_path.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
            print(f"[OK] 디렉터리 동기화 완료: {dir_rel} -> {dst_path}")
            success_count += 1
        except Exception as e:
            print(f"[ERR] 디렉터리 동기화 실패 ({dir_rel}): {e}")

    # 2. 핵심 파일 동기화 (AGENTS.md 등 규칙/문서)
    for file_rel in SYNC_FILES:
        src_file = src_base / file_rel
        dst_file = dst_base / file_rel

        if not src_file.exists():
            print(f"[SKIP] 소스 파일이 없어 건너뜁니다: {file_rel}")
            continue

        try:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            print(f"[OK] 파일 동기화 완료: {file_rel} -> {dst_file}")
            success_count += 1
        except Exception as e:
            print(f"[ERR] 파일 동기화 실패 ({file_rel}): {e}")

    print(f"\n[DONE] 총 {success_count}개 항목 동기화 완료!")
    return success_count > 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="데스크톱과 작업 공간 간 동기화 도구")
    parser.add_argument(
        "--pull",
        "--from-desktop",
        action="store_true",
        help="데스크톱 폴더에서 작업 공간으로 최신 규칙/파일을 동기화합니다.",
    )
    args = parser.parse_args()

    ok = sync_codebase(from_desktop=args.pull)
    sys.exit(0 if ok else 1)
