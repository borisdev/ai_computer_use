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
    # ⚠️ `docs/_parts/` holds FRAGMENTS that are inlined into a generated file
    # at the repo root, so their relative links resolve from THERE, not from
    # where the fragment sits. Checking them in place reports false breaks --
    # and the links themselves are checked in the assembled document.
    docs = [
        p
        for p in sorted((ROOT / "docs").rglob("*.md")) + sorted(ROOT.glob("*.md"))
        if "_parts" not in p.parts
    ]
    for doc in docs:
        for match in LINK.finditer(doc.read_text()):
            target = match.group(1)
            rel = doc.relative_to(ROOT)
            # ⛔ SAME-FILE ANCHORS WERE SKIPPED WITH THE EXTERNAL ONES, so a
            # table of seven `#section` links could be entirely wrong and this
            # script printed "0 broken". Cross-file `path#frag` was checked
            # below all along, which is exactly why the hole was invisible --
            # the feature appeared to exist. Caught by breaking one on purpose
            # and watching the check stay green.
            if target.startswith("#"):
                anchors = {slug(h) for h in HEADING.findall(doc.read_text())}
                if target[1:] not in anchors:
                    faults.append(f"{rel}: no such anchor in this file -> {target}")
                continue
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path, _, fragment = target.partition("#")
            resolved = (doc.parent / path).resolve()
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
