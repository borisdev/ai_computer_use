#!/usr/bin/env python3
"""Propose ParaBank's `TABLE_CONTROL_PANEL`s by DISCOVERY, and store them.

The counterpart to `scripts/add_panels.py`, which measured the same regions from
the same screenshots BY HAND -- and the reason issue #6 was open. Run them both
and the store holds both, under different ids, which is the comparison worth
having: `accounts_table_panel` was measured by a person and
`accounts_overview_table_control_panel` by `screenshot2panels`.

    ./scripts/discover_panels.py                     # every screen below
    ./scripts/discover_panels.py --screen overview   # just one

It reads the SAME committed screenshots `add_panels.py` reads, so the two are
comparable and neither needs a browser. Every number in what it writes is
measured from those pixels; the model is asked only what a region IS.

⚠️ It spends model calls -- one read, one placement, and a refinement per region.

⚠️ Idempotent, and that takes two rules rather than one. `merge_panels` replaces
a panel already stored under the same id -- but a re-run can propose a DIFFERENT
set, and the first version of this script left the ones it no longer proposed
behind: a `09_26_2026_table_control_panel` from a run that read the news list as
a table sat in the map after the run that refused it. So every panel discovery
NAMED is dropped first, which is the `_table_control_panel` suffix `_slug` gives
them. The hand-measured panels -- `accounts_table_panel`, `account_details_panel`,
`account_services_nav`, `loan_result_panel` -- are outside that namespace and are
left exactly where `add_panels.py` put them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from interfaceai.control_map_store import ControlMapStore, MapKey
from interfaceai.screenshot2controls import ControlRole, ImageSize, ScreenInput, ScreenOutput
from interfaceai.screenshot2panels import extract_panel_locators, merge_panels
from interfaceai.surface import OffLoop
from interfaceai.vision_llm import call_vision_llm

# The same three screenshots `scripts/add_panels.py` measured by hand.
SHOTS = {
    "index": ROOT / "evidence" / "runs" / "20260926T022551Z" / "frames" / "001-00-index.png",
    "overview": ROOT / "evidence" / "runs" / "20260926T022551Z" / "frames" / "004-03-overview.png",
    "activity": ROOT / "tests" / "fixtures" / "activity-13344.png",
    "requestloan": ROOT / "tests" / "fixtures" / "loan-result.png",
}


# `_slug(label, ControlRole.TABLE_CONTROL_PANEL)` ends every discovered panel's id
# with this, and nothing hand-measured does.
_DISCOVERED_SUFFIX = f"_{ControlRole.TABLE_CONTROL_PANEL.value}"


def _without_discovered(control_map: ScreenOutput) -> ScreenOutput:
    """Drop the panels a PREVIOUS run of this script named. See the module note."""
    return control_map.model_copy(
        update={
            "controls": [
                c
                for c in control_map.controls
                if not (
                    c.role is ControlRole.TABLE_CONTROL_PANEL and c.id.endswith(_DISCOVERED_SUFFIX)
                )
            ]
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screen", choices=sorted(SHOTS), action="append")
    parser.add_argument("--maps", type=Path, default=ROOT / "control_maps")
    parser.add_argument("--dry-run", action="store_true", help="propose, print, write nothing")
    args = parser.parse_args()

    store = ControlMapStore(args.maps)
    screens = args.screen or sorted(SHOTS)
    faults = 0

    with OffLoop() as off:
        for screen in screens:
            shot = SHOTS[screen]
            proposed = off.run(
                extract_panel_locators(
                    ScreenInput(screenshot_png=shot.read_bytes()), vision=call_vision_llm
                )
            )
            print(f"{screen}: {len(proposed)} region(s) read from {shot.name}")
            for panel in proposed:
                if panel.status == "ready":
                    spec = panel.panel
                    assert spec is not None
                    print(
                        f"  ✅ {panel.id}: {spec.columns} key={spec.key_column} "
                        f"pitch={spec.row_pitch} {spec.width}x{spec.height}"
                        f"{' openable' if spec.key_click_dx is not None else ' read-only'}"
                    )
                else:
                    # A refusal is the point, not a failure -- print it in full so
                    # the reason is reviewable rather than a count.
                    print(f"  ⛔ {panel.id}: {panel.reason}")
            ready = [p for p in proposed if p.status == "ready"]
            if not ready:
                # Not an error: a screen may genuinely hold no repeated
                # structure. `index` has three; the login form is not one.
                print(f"  (nothing storable for {screen})")
                continue
            if args.dry_run:
                continue
            for tenant in store.tenants("parabank"):
                key = MapKey(app="parabank", tenant=tenant, screen=screen)
                recorded = store.screens("parabank", tenant)
                if screen in recorded:
                    store.put(key, merge_panels(_without_discovered(store.get(key)), ready))
                else:
                    # Same choice `add_panels.py` makes for activity.htm: a map
                    # holding only the panel is honest, not a placeholder.
                    store.put(
                        key,
                        merge_panels(
                            ScreenOutput(
                                screenshot_sha256="0" * 64,
                                image_size=ImageSize(width=1280, height=900),
                                controls=[],
                            ),
                            ready,
                        ),
                    )
                print(f"    stored into {tenant}/{screen}")
    return faults


if __name__ == "__main__":
    raise SystemExit(main())
