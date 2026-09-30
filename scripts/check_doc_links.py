#!/usr/bin/env python3
"""Every link that points INTO this repo resolves -- relative or absolute.

This repo's docs cross-reference heavily and carry the measurements the code
cannot state, so a dead link is a lost finding. Written after a hand-guessed
heading anchor shipped broken: GitHub drops a leading emoji WITHOUT leaving a
hyphen, which is not what you would guess and not something review catches.

⛔ **The absolute half was added after it was needed.** `CAPABILITIES.md` is
generated and links every artifact and evidence run as a full
`github.com/borisdev/...` URL, which the relative check skipped entirely -- so
THREE links pointed at run directories that are not in the repo, one of them to a
run that exists only on the machine that made it. `evidence/` is a graded
deliverable (brief S6); a reviewer clicking through it gets a 404, and nothing
said so.

⚠️ The `evidence/runs/` half also checks the other direction: a committed run
NOTHING links to is either a lost reference or a scratch run that slipped past
`.gitignore`. Those runs are committed by exception with `git add -f`, so the
exception should be visible from a document.

Exits 1 on the first broken path or anchor. Run it before pushing docs.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\]\(([^)]+)\)")
HEADING = re.compile(r"^#+\s+(.*)$", re.MULTILINE)
# A link into this repo's own tree, as GitHub spells it in a generated document.
# ⚠️ Stops at a quote and an angle bracket as well as `)`: the generated
# document is HTML, so its URLs are delimited by `"`, and the first version of
# this swallowed the rest of the table cell.
IN_REPO = re.compile(
    r"https://github\.com/borisdev/ai_computer_use/(?:blob|tree)/main/([^)#\"'<>\s]+)"
)
RUN = re.compile(r"evidence/runs/(2026\d{4}T\d{6}Z)")
RUN_ID = re.compile(r"(2026\d{4}T\d{6}Z)")


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
        for p in sorted((ROOT / "docs").rglob("*.md"))
        + sorted(ROOT.glob("*.md"))
        # evidence/README.md is the index OF the graded deliverable and links
        # every committed run. Leaving it out made the run check report every
        # run it is the only reference for.
        + [ROOT / "evidence" / "README.md"]
        if "_parts" not in p.parts
    ]
    for doc in docs:
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

    tracked = set(
        subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.split()
    )
    linked_runs: set[str] = set()
    for doc in docs:
        text = doc.read_text()
        rel = doc.relative_to(ROOT)
        for path in IN_REPO.findall(text):
            # TRACKED, not merely present: a path that exists only on this
            # machine is exactly the failure this half was written for.
            if path.rstrip("/") not in tracked and not any(
                t.startswith(path.rstrip("/") + "/") for t in tracked
            ):
                faults.append(f"{rel}: links a path this repo does not track -> {path}")
        # The ID itself, not only `evidence/runs/<id>`: the two runs kept as test
        # fixtures are named in prose, and a named run is a referenced run.
        linked_runs |= set(RUN_ID.findall(text))

    committed_runs = {m.group(1) for t in tracked if (m := RUN.match(t))}
    for run in sorted(committed_runs - linked_runs):
        faults.append(f"evidence/runs/{run}: committed but no document links it")

    for fault in faults:
        print(f"BROKEN  {fault}")
    print(f"\n{len(faults)} broken link(s)")
    return 1 if faults else 0


if __name__ == "__main__":
    sys.exit(main())
