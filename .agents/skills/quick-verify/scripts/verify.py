"""Quick verification script for chzzk_downloader.

Runs Ruff check, Ruff format check, Pyrefly type check, and Pytest suites.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def run_command(name: str, cmd: list[str]) -> bool:
    print("\n==========================================")
    print(f"[*] Running: {name}")
    print(f"    Command: {' '.join(cmd)}")
    print("==========================================")
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print(f"[+] {name}: PASSED\n")
        return True
    else:
        print(f"[-] {name}: FAILED (exit code: {result.returncode})\n")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Quick verification runner for chzzk_downloader"
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Run only catalog/integration smoke tests instead of full 260+ suite",
    )
    args = parser.parse_args()

    steps: list[tuple[str, list[str]]] = [
        ("Ruff Linter", ["uv", "run", "--no-sync", "ruff", "check", "."]),
        (
            "Ruff Formatter",
            ["uv", "run", "--no-sync", "ruff", "format", "--check", "."],
        ),
        ("Pyrefly Type Check", ["uv", "run", "--no-sync", "pyrefly", "check"]),
        (
            "Rules Ratchet Check",
            ["uv", "run", "--no-sync", "python", "tools/check_rules.py"],
        ),
    ]

    if args.fast:
        steps.append(
            (
                "Pytest (Smoke - UI Feedback Catalog)",
                [
                    "uv",
                    "run",
                    "--no-sync",
                    "pytest",
                    "tests/test_ui_feedback_catalog.py",
                ],
            )
        )
    else:
        steps.append(("Pytest (Full Suite)", ["uv", "run", "--no-sync", "pytest"]))

    results: dict[str, bool] = {}
    for name, cmd in steps:
        success = run_command(name, cmd)
        results[name] = success
        if not success:
            print(f"\n[!] Verification halted due to failure in '{name}'.")
            break

    print("\n================== Verification Summary ==================")
    all_passed = True
    for name, success in results.items():
        status = "PASSED" if success else "FAILED"
        if not success:
            all_passed = False
        print(f"  - {name:<35}: {status}")
    print("==========================================================")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
