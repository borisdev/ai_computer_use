#!/usr/bin/env python3
"""Add ParaBank's two TABLE_CONTROL_PANELs to their control maps.

⚠️ **This stands in for a discovery step that does not exist yet.** Discovery
inventories interactive controls; it has no notion of a region with structure,
so a `TABLE_CONTROL_PANEL` has to be put in by hand. Doing it as a committed,
re-runnable script rather than a scratch edit means the geometry below is
reviewable and the map can be rebuilt.

Every number here was measured, not guessed:

    anchor      the 'Account' COLUMN HEADER, not the header row. Columns
                auto-size, so a patch spanning a boundary moves when the row
                count changes -- measured 0.0000 against the 1-row table, where
                a single header cell scores 1.0000.
    panel       the region to crop and read, relative to the matched anchor.
    key_column  a narrow band over the account numbers, used to measure the row
                rhythm (28px at 0.899) so a row index becomes a click point.

    ./scripts/add_panels.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from interfaceai.control_map_store import ControlMapStore, MapKey
from interfaceai.screenshot2controls import (
    ClickPoint,
    ControlPolicy,
    ControlRole,
    CropBox,
    ImageSize,
    LocatedControl,
    PanelSpec,
    ScreenInput,
    ScreenOutput,
    _make_locator,
)

OVERVIEW_SHOT = ROOT / "evidence" / "runs" / "20260926T022551Z" / "frames" / "004-03-overview.png"
ACTIVITY_SHOT = ROOT / "tests" / "fixtures" / "activity-13344.png"

# --- overview.htm: eleven accounts, one row each ----------------------------
#
# key_click_dx: the account NUMBER is the link, and it sits at x 492..525 with
# its centre at 508. The anchor's click point is (490, 320), so the offset is
# 508 - 490 = 18. That is what turns a row INDEX into a click without ever
# grounding the row -- docs/issues/0009.
ACCOUNTS = LocatedControl(
    id="accounts_table_panel",
    label="Account",
    role=ControlRole.TABLE_CONTROL_PANEL,
    description="The accounts table: one row per account, anchored on its 'Account' header.",
    status="ready",
    click_point=ClickPoint(x=490, y=320),
    locator=None,  # filled in below
    policy=ControlPolicy(irreversible=False, sensitive=True),
    panel=PanelSpec(
        columns=("account_id", "balance", "available"),
        key_column="account_id",
        dx=-20,
        dy=28,
        width=310,
        height=320,
        key_dx=0,
        key_dy=28,
        key_width=40,
        key_click_dx=18,
        # Measured by autocorrelation on the seeded table: 28px at 0.899,
        # next candidate 0.385. Used ONLY when a shrunken table has too few
        # rows for a live measurement to find a period.
        row_pitch=28,
    ),
)
ACCOUNTS_ANCHOR = (CropBox(x=486, y=316, width=90, height=28), ClickPoint(x=490, y=320))

# --- activity.htm: a label/value table, four rows ---------------------------
#
# Measured: labels x 490..592, values x 594..653, rows 23px apart from y=316.
# Anchoring on "Account Number:" -- a single cell, because columns auto-size
# and a patch spanning a boundary moves (docs/issues/0011).
#
# key_click_dx is None: these rows are text, not links. The panel is readable
# and not openable, and the schema says so rather than leaving it to a comment.
DETAILS = LocatedControl(
    id="account_details_panel",
    label="Account Number:",
    role=ControlRole.TABLE_CONTROL_PANEL,
    description="The account detail table: one row per field, anchored on 'Account Number:'.",
    status="ready",
    click_point=ClickPoint(x=495, y=326),
    locator=None,
    policy=ControlPolicy(irreversible=False, sensitive=True),
    panel=PanelSpec(
        columns=("field", "value"),
        key_column="field",
        dx=-10,
        dy=-16,
        width=190,
        height=104,
        key_dx=-10,
        key_dy=-16,
        key_width=110,
        # Measured from the DOM oracle: rows at y 316, 339, 362, 385.
        row_pitch=23,
    ),
)
DETAILS_ANCHOR = (CropBox(x=488, y=314, width=106, height=25), ClickPoint(x=495, y=326))


def _anchored(control: LocatedControl, shot: Path, anchor, point) -> LocatedControl:
    return control.model_copy(
        update={
            "locator": _make_locator(ScreenInput(screenshot_png=shot.read_bytes()), anchor, point)
        }
    )


def main() -> int:
    store = ControlMapStore(ROOT / "control_maps")
    panels = {
        "overview": _anchored(ACCOUNTS, OVERVIEW_SHOT, *ACCOUNTS_ANCHOR),
        "activity": _anchored(DETAILS, ACTIVITY_SHOT, *DETAILS_ANCHOR),
    }
    for tenant in store.tenants("parabank"):
        recorded = store.screens("parabank", tenant)
        for screen, panel in panels.items():
            key = MapKey(app="parabank", tenant=tenant, screen=screen)
            if screen in recorded:
                control_map = store.get(key)
                controls = [c for c in control_map.controls if c.id != panel.id] + [panel]
                store.put(key, control_map.model_copy(update={"controls": controls}))
            else:
                # activity.htm was never inventoried -- the panel is the only
                # thing any capability needs from it, so a map holding just the
                # panel is honest rather than a placeholder.
                store.put(
                    key,
                    ScreenOutput(
                        screenshot_sha256="0" * 64,
                        image_size=ImageSize(width=1280, height=900),
                        controls=[panel],
                    ),
                )
            print(f"  {tenant}/{screen}: {panel.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
