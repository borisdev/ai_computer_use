#!/usr/bin/env python3
"""Add the accounts-table panel to ParaBank's overview control map.

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

    ./scripts/add_accounts_panel.py
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
    LocatedControl,
    PanelSpec,
    ScreenInput,
    _make_locator,
)

RECORDED = ROOT / "evidence" / "runs" / "20260926T022551Z" / "frames" / "004-03-overview.png"
PANEL_ID = "accounts_table_panel"

SPEC = PanelSpec(
    columns=("account_id", "balance", "available"),
    key_column="account_id",
    dx=-20,
    dy=28,
    width=310,
    height=320,
    key_dx=0,
    key_dy=28,
    key_width=40,
)


def build() -> LocatedControl:
    anchor = _make_locator(
        ScreenInput(screenshot_png=RECORDED.read_bytes()),
        CropBox(x=486, y=316, width=90, height=28),
        ClickPoint(x=490, y=320),
    )
    return LocatedControl(
        id=PANEL_ID,
        label="Account",
        role=ControlRole.TABLE_CONTROL_PANEL,
        description="The accounts table: one row per account, anchored on its 'Account' header.",
        status="ready",
        click_point=ClickPoint(x=490, y=320),
        locator=anchor,
        # A panel is read, never clicked, and the balances on it are a
        # customer's financial data.
        policy=ControlPolicy(irreversible=False, sensitive=True),
        panel=SPEC,
    )


def main() -> int:
    store = ControlMapStore(ROOT / "control_maps")
    panel = build()
    for tenant in store.tenants("parabank"):
        key = MapKey(app="parabank", tenant=tenant, screen="overview")
        if "overview" not in store.screens("parabank", tenant):
            print(f"  skip {tenant}: no overview map recorded")
            continue
        control_map = store.get(key)
        controls = [c for c in control_map.controls if c.id != PANEL_ID] + [panel]
        store.put(key, control_map.model_copy(update={"controls": controls}))
        print(f"  {tenant}/overview: {PANEL_ID} added ({len(controls)} controls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
