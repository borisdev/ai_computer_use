#!/usr/bin/env python3
"""Write the real test counts into every document that states them.

    uv run python3 scripts/sync_test_counts.py          # rewrite
    uv run python3 scripts/sync_test_counts.py --check  # fail if stale

⚠️ Three documents stated three different numbers -- 247, 249 and 257 -- in the
same commit where one of them warned about stale counts. Copilot found it on
PR #5's third pass. A number a human retypes in three places is a number that
will disagree with itself.

`tests/test_docs.py` asserts the three AGREE, which is static and cheap. Only
this script can say whether they are RIGHT, because that needs a real
collection run.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("README.md", "REPORT.md", "HANDOFF.md")
PATTERN = re.compile(r"(\d+) tests? [—-] (\d+) offline, (\d+) live")
HANDOFF = re.compile(r"(\d+) tests \((\d+) offline, (\d+) live\)")


def counted() -> tuple[int, int, int]:
    def run(*args: str) -> int:
        out = subprocess.run(
            ["uv", "run", "pytest", "-q", "--collect-only", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        ).stdout
        match = re.search(r"(\d+)/(\d+) tests collected", out) or re.search(
            r"(\d+) tests? collected", out
        )
        if not match:
            raise RuntimeError(f"could not read a count from pytest:\n{out[-400:]}")
        return int(match.group(1))

    live = run("-m", "live")
    offline = run("-m", "not live")
    return offline + live, offline, live


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    total, offline, live = counted()
    print(f"counted: {total} tests — {offline} offline, {live} live")

    stale: list[str] = []
    for name in DOCS:
        path = ROOT / name
        text = path.read_text()
        fixed = PATTERN.sub(f"{total} tests — {offline} offline, {live} live", text)
        fixed = HANDOFF.sub(f"{total} tests ({offline} offline, {live} live)", fixed)
        if fixed == text:
            continue
        stale.append(name)
        if not args.check:
            path.write_text(fixed)

    if args.check and stale:
        print(f"STALE: {', '.join(stale)} — run without --check")
        return 1
    print(f"  {'stale' if args.check else 'updated'}: {', '.join(stale) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
