#!/usr/bin/env python3
"""Does the coarse inventory name the same controls the same way twice?

A5 says `control_id` should be a closed enum rather than a free string. The
argument for it rests on a measurement taken while the READ pass was fighting
the grid overlay -- the defect A4 removed. So re-measure before building.

DESIGN. One screenshot, three draws. Reusing a single image is the whole point:
it isolates the model's nondeterminism from any variation in the page, so a
difference between runs can only have come from the model.

Refinement is skipped (`only=[]`). It costs ~20 vision calls per screen and
decides GROUNDING, not naming, which is what is being measured here.

    uv run python3 scripts/measure_naming_churn.py [--screen overview] [--runs 3]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from interfaceai.screenshot2controls import ScreenInput, extract_control_locators
from interfaceai.settings import get_settings
from interfaceai.surface import OffLoop, PlaywrightSurface
from interfaceai.vision_llm import call_vision_llm

SCREENS = {
    "overview": "/overview.htm",
    "requestloan": "/requestloan.htm",
    "transfer": "/transfer.htm",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--screen", default="overview", choices=sorted(SCREENS))
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()

    settings = get_settings()
    with PlaywrightSurface(allowed_origins=settings.allowed_origins) as surface, OffLoop() as off:
        page = surface.page
        surface.navigate(f"{settings.parabank_base_url}/index.htm")
        page.fill("input[name='username']", settings.parabank_demo_username)
        page.fill("input[name='password']", settings.parabank_demo_password.get_secret_value())
        page.click("input[value='Log In']")
        page.wait_for_load_state("networkidle")
        page.goto(f"{settings.parabank_base_url}{SCREENS[args.screen]}")
        page.wait_for_load_state("networkidle")
        surface.wait(1.0)

        shot = surface.screenshot()  # ONE image, reused
        print(f"{args.screen}: one screenshot, {args.runs} draws\n")

        runs: list[list[str]] = []
        for i in range(args.runs):
            out = off.run(
                extract_control_locators(
                    ScreenInput(screenshot_png=shot), vision=call_vision_llm, only=[]
                )
            )
            ids = sorted(c.id for c in out.controls)
            runs.append(ids)
            print(f"  run {i + 1}: {len(ids)} controls")

    stable = set(runs[0]).intersection(*(set(r) for r in runs[1:]))
    everything = sorted(set().union(*(set(r) for r in runs)))
    seen = Counter(i for r in runs for i in set(r))

    print(f"\n{'id':<34} {'runs':>4}")
    print("-" * 40)
    for cid in everything:
        mark = "" if seen[cid] == len(runs) else "   <-- churn"
        print(f"{cid:<34} {seen[cid]:>4}{mark}")

    counts = {len(r) for r in runs}
    print(
        f"\nstable across all {len(runs)}: {len(stable)}"
        f"\nnames seen at least once:  {len(everything)}"
        f"\nchurned:                   {len(everything) - len(stable)}"
        f"\ncontrol count per run:     {sorted(counts)}"
    )
    verdict = (
        "STABLE -- a closed enum would add enforcement, not correctness"
        if len(stable) == len(everything)
        else "CHURN -- A5 has a live failing case"
    )
    print(f"\n{verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
