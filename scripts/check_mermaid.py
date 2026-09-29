#!/usr/bin/env python3
"""Render every mermaid block in the docs. A diagram that does not parse is a
broken picture in a graded deliverable.

    uv run python3 scripts/check_mermaid.py [file ...]

GitHub renders an error box rather than failing loudly, so a malformed block
looks like a diagram until someone scrolls to it. Needs `npx`; it fetches
@mermaid-js/mermaid-cli on first run and uses its own headless Chromium, so
this is the one check here that touches the network.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ["README.md", "docs/flows.md", "REPORT.md", "docs/status.md"]
# Chromium in a container needs this; mermaid-cli offers no flag for it.
PUPPETEER = '{"args":["--no-sandbox","--disable-dev-shm-usage"]}'


def main() -> int:
    targets = [Path(a) for a in sys.argv[1:]] or [ROOT / f for f in DEFAULT]
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "puppeteer.json"
        cfg.write_text(PUPPETEER)
        for path in targets:
            if not path.exists():
                continue
            blocks = re.findall(r"```mermaid\n(.*?)```", path.read_text(), re.DOTALL)
            for i, block in enumerate(blocks, 1):
                src = Path(tmp) / f"{path.stem}-{i}.mmd"
                src.write_text(block)
                out = subprocess.run(
                    ["npx", "-y", "@mermaid-js/mermaid-cli@11", "-p", str(cfg),
                     "-i", str(src), "-o", str(src.with_suffix(".svg"))],
                    capture_output=True, text=True, timeout=180, check=False,
                )
                kind = block.strip().splitlines()[0][:22]
                if out.returncode == 0 and src.with_suffix(".svg").exists():
                    print(f"  ok    {path.name}[{i}] {kind}")
                else:
                    bad += 1
                    err = (out.stderr or out.stdout).strip().splitlines()
                    print(f"  BROKEN {path.name}[{i}] {kind}")
                    for line in err[-4:]:
                        print(f"         {line}")
    print(f"\n{bad} broken diagram(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
