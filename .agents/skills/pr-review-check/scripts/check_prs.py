"""Open PRs Review Comments Checker for chzzk_downloader."""

from __future__ import annotations

import json
import subprocess
import sys

# Configure UTF-8 stdout/stderr for Windows console compatibility
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def run_gh_json(args: list[str]) -> dict | list | None:
    try:
        res = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if res.returncode != 0:
            return None
        return json.loads(res.stdout)
    except Exception:
        return None


def main() -> int:
    repo = "Yumetri/chzzk_downloader"
    if len(sys.argv) > 1:
        repo = sys.argv[1]

    print(f"[*] Checking open PRs in {repo}...")
    prs = run_gh_json(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--json",
            "number,title,headRefName,updatedAt,url",
        ]
    )

    if not prs:
        print("[-] No open PRs found or failed to fetch.")
        return 0

    print(f"[+] Found {len(prs)} open PRs. Inspecting reviews & comments...\n")

    has_attention_needed = False
    for pr in prs:
        num = pr["number"]
        title = pr["title"]
        branch = pr["headRefName"]
        url = pr["url"]

        detail = run_gh_json(
            [
                "pr",
                "view",
                str(num),
                "--repo",
                repo,
                "--json",
                "comments,reviews",
            ]
        )

        comments = detail.get("comments", []) if detail else []
        reviews = detail.get("reviews", []) if detail else []

        # Find external reviews / comments
        all_feedback = []
        for c in comments:
            author = c.get("author", {}).get("login", "")
            body = c.get("body", "").strip()
            created_at = c.get("createdAt", "")
            all_feedback.append((created_at, author, body, "Comment"))

        for r in reviews:
            author = r.get("author", {}).get("login", "")
            body = r.get("body", "").strip()
            state = r.get("state", "")
            created_at = r.get("submittedAt", "")
            if body or state not in ("APPROVED", "COMMENTED"):
                all_feedback.append((created_at, author, f"[{state}] {body}", "Review"))

        all_feedback.sort(key=lambda x: x[0], reverse=True)

        print("━" * 70)
        print(f"PR #{num}: {title}")
        print(f"Branch: {branch} | URL: {url}")

        if not all_feedback:
            print("  -> (No comments or reviews yet)")
        else:
            has_attention_needed = True
            latest = all_feedback[0]
            print(f"  -> Total Feedback Count: {len(all_feedback)}")
            print(f"  -> Latest by @{latest[1]} ({latest[3]}, {latest[0]}):")
            # Truncate preview
            preview_lines = [
                line.strip() for line in latest[2].splitlines() if line.strip()
            ]
            preview_text = " / ".join(preview_lines[:2])
            if len(preview_text) > 100:
                preview_text = preview_text[:97] + "..."
            print(f'     "{preview_text}"')

    print("━" * 70)
    if has_attention_needed:
        print("[!] Feedback detected. Review comments above to respond.")
    else:
        print("[✓] All PRs clean. No pending feedback.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
