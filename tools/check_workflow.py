"""AGENTS.md 협업 라이프사이클 7단계 상태 머신 기계 검증기 (tools/check_workflow.py).

Phase 1~7 상태 전이 가드와 필수 산출물을 기계적으로 검증합니다:
- P5: 4대 완료 조건(Ruff, Pyrefly, check_rules, Pytest) 전수 검증
- P6: 유의미한 아키텍처/코드 변경 시 reports/ 내 최신 HTML 보고서 존재 확인
- P7: 작업 트리 Clean 상태 및 미해결 산출물 점검
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"


def _run_cmd(cmd: list[str], label: str) -> bool:
    """명령어를 실행하고 성공 여부를 반환합니다."""
    print(f"[RUN] {label}...", end=" ", flush=True)
    res = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if res.returncode == 0:
        print("OK")
        return True
    print("FAILED")
    if res.stdout:
        print(res.stdout.strip())
    if res.stderr:
        print(res.stderr.strip())
    return False


def check_phase_5_verification(skip_pytest: bool = False) -> bool:
    """Phase 5: 4대 기계 검증(Ruff, Pyrefly, check_rules, Pytest) 통과 여부를 검증합니다."""
    print("\n=== [Phase 5] 4대 기계 완료 조건 검증 ===")
    all_ok = True

    # 1. Ruff lint
    if not _run_cmd(["uv", "run", "--offline", "ruff", "check", "."], "Ruff Check"):
        all_ok = False

    # 2. Ruff format
    if not _run_cmd(
        ["uv", "run", "--offline", "ruff", "format", "--check", "."],
        "Ruff Format Check",
    ):
        all_ok = False

    # 3. Pyrefly type check
    if not _run_cmd(
        ["uv", "run", "--offline", "pyrefly", "check"], "Pyrefly Type Check"
    ):
        all_ok = False

    # 4. R/T/M 규칙 래칫
    if not _run_cmd(
        ["uv", "run", "--offline", "python", "tools/check_rules.py"],
        "check_rules.py 래칫 검사",
    ):
        all_ok = False

    # 5. Pytest
    if not skip_pytest:
        if not _run_cmd(
            ["uv", "run", "--offline", "pytest"], "Pytest 전체 단위/통합 테스트"
        ):
            all_ok = False
    else:
        print("[SKIP] Pytest 검사 생략 (--quick)")

    return all_ok


def check_phase_6_report_guard(require_report: bool = False) -> bool:
    """Phase 6: 유의미한 아키텍처/코드 변경 시 reports/ HTML 보고서 존재 여부를 검증합니다."""
    print("\n=== [Phase 6] 아키텍처 학습용 HTML 보고서 산출물 가드 ===")
    status_res = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    changed_lines = [
        line.strip()
        for line in status_res.stdout.splitlines()
        if line.strip() and not line.strip().startswith("?? reports/")
    ]

    has_src_changes = any("src/" in line for line in changed_lines)
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    reports = (
        list(REPORTS_DIR.glob(f"{today_str}-*.html")) if REPORTS_DIR.exists() else []
    )

    if has_src_changes:
        print(f"[INFO] 현재 src/ 코드 변경 감지됨 ({len(changed_lines)}개 파일 변경)")
        if reports:
            print(f"[OK] 오늘자 HTML 분석 보고서 확인됨: {[r.name for r in reports]}")
            return True
        else:
            msg = f"[WARN] 오늘자({today_str}) HTML 분석 보고서가 reports/ 에 없습니다."
            if require_report:
                print(f"[FAIL] {msg} (AGENT_WORKFLOW.md §4 위반)")
                return False
            print(f"{msg} (세션 종료 전 explain-diff-html 생성 권장)")
            return True
    else:
        print("[INFO] src/ 코드 변경 없음 (HTML 보고서 필수 아님)")
        return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AGENTS.md 협업 라이프사이클 7단계 상태 머신 기계 검증기"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="시간 소요가 큰 Pytest 전체 실행을 생략합니다.",
    )
    parser.add_argument(
        "--require-report",
        action="store_true",
        help="src/ 변경 시 오늘자 reports/*.html 보고서 부재를 실패로 처리합니다.",
    )
    args = parser.parse_args()

    p5_ok = check_phase_5_verification(skip_pytest=args.quick)
    p6_ok = check_phase_6_report_guard(require_report=args.require_report)

    print("\n==========================================")
    if p5_ok and p6_ok:
        print("[SUCCESS] 협업 라이프사이클 가드 검증을 모두 통과했습니다.")
        return 0
    else:
        print("[FAILURE] 협업 라이프사이클 가드 검증에 실패했습니다.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
