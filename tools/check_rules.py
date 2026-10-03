"""AGENTS.md 기계 검증기. CI와 로컬에서 `uv run python tools/check_rules.py`로 실행한다.

규칙은 AGENTS.md의 R-번호와 1:1로 대응한다. 현재 위반 수는 tools/rule_baseline.json에
기록된 값까지만 허용(래칫)하며, 기준값보다 늘어나면 실패한다. 줄어들면 기준값을 함께 낮춘다.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "chzzk_downloader"
TESTS = ROOT / "tests"
BASELINE = ROOT / "tools" / "rule_baseline.json"

MAX_FILE_LINES = 400

# (규칙 ID, 대상 디렉터리, 정규식, 설명)
PATTERNS: list[tuple[str, Path, str, str]] = [
    (
        "R1-core-qt",
        SRC / "core",
        r"^\s*(from|import)\s+PyQt6",
        "core/에서 PyQt6 import",
    ),
    ("R3-hasattr", SRC, r"\bhasattr\(", "hasattr() 사용"),
    ("R3-getattr", SRC, r"\bgetattr\(", "getattr() 사용"),
    ("R3-sip", SRC, r"\bsip\.isdeleted\(", "sip.isdeleted() 사용"),
    ("R4-blind-except", SRC, r"except\s+Exception\b", "except Exception"),
    (
        "R6-ui-io",
        SRC / "gui",
        r"subprocess\.(run|call|check_output)\(|urlopen\(|\.mkdir\(",
        "GUI 계층의 동기 I/O",
    ),
    ("T1-sleep", TESTS, r"\btime\.sleep\(", "테스트의 time.sleep"),
    ("T2-called", TESTS, r"\.called\b", "테스트의 .called 단언"),
    ("T3-private", TESTS, r"\.\_[a-z]\w*", "테스트의 private 속성 접근"),
    (
        "M1-ticket-words",
        TESTS,
        r"\bP[0-3]\b|(?i:adversarial)|결함|라운드",
        "테스트 내 티켓/감사 메타 단어",
    ),
]


def _py_files(base: Path) -> list[Path]:
    return [p for p in base.rglob("*.py") if "__pycache__" not in p.parts]


def count_violations() -> dict[str, int]:
    counts: dict[str, int] = {}
    for rule_id, base, pattern, _ in PATTERNS:
        rx = re.compile(pattern)
        n = 0
        for f in _py_files(base):
            for line in f.read_text(encoding="utf-8").splitlines():
                if rx.search(line):
                    n += 1
        counts[rule_id] = n

    long_files = [
        f
        for f in _py_files(SRC)
        if len(f.read_text(encoding="utf-8").splitlines()) > MAX_FILE_LINES
    ]
    counts["R2-file-lines"] = len(long_files)

    meta_test_files = [
        f
        for f in _py_files(TESTS)
        if re.search(r"(?i)(p[0-3]_|adversarial|round\d|defect)", f.name)
    ]
    counts["M2-ticket-test-files"] = len(meta_test_files)
    return counts


def main() -> int:
    counts = count_violations()
    if "--write-baseline" in sys.argv:
        BASELINE.write_text(
            json.dumps(counts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"baseline written: {BASELINE}")
        return 0

    baseline: dict[str, int] = (
        json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    )
    failed = False
    for rule_id, n in sorted(counts.items()):
        allowed = baseline.get(rule_id, 0)
        mark = "OK " if n <= allowed else "FAIL"
        if n > allowed:
            failed = True
        print(f"[{mark}] {rule_id:<22} {n:>4} (허용 {allowed})")
    if failed:
        print("\n위반이 기준값보다 늘었습니다. AGENTS.md의 해당 R-규칙을 확인하세요.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
