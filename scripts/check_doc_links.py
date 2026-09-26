#!/usr/bin/env python3
"""Every relative link and image path in docs/ resolves, anchors included.

This repo's docs cross-reference heavily and carry the measurements the code
cannot state, so a dead link is a lost finding. Written after a hand-guessed
heading anchor shipped broken: GitHub drops a leading emoji WITHOUT leaving a
hyphen, which is not what you would guess and not something review catches.

Exits 1 on the first broken path or anchor. Run it before pushing docs.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\]\(([^)]+)\)")
HEADING = re.compile(r"^#+\s+(.*)$", re.MULTILINE)


def slug(heading: str) -> str:
    """GitHub's anchor rule: lowercase, drop punctuation and emoji, spaces -> hyphens."""
    return re.sub(r"[^a-z0-9 -]", "", heading.lower()).strip().replace(" ", "-")


def main() -> int:
    faults: list[str] = []
    for doc in sorted((ROOT / "docs").rglob("*.md")):
        for match in LINK.finditer(doc.read_text()):
            target = match.group(1)
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            path, _, fragment = target.partition("#")
            resolved = (doc.parent / path).resolve()
            rel = doc.relative_to(ROOT)
            if not resolved.exists():
                faults.append(f"{rel}: missing path -> {target}")
                continue
            if fragment and resolved.suffix == ".md":
                anchors = {slug(h) for h in HEADING.findall(resolved.read_text())}
                if fragment not in anchors:
                    faults.append(f"{rel}: no such anchor -> #{fragment}")

    for fault in faults:
        print(f"BROKEN  {fault}")
    print(f"\n{len(faults)} broken link(s)")
    return 1 if faults else 0


if __name__ == "__main__":
    sys.exit(main())
