"""Capability 1 end to end, through the real mechanisms only.

`live` — needs ParaBank up and seeded, and spends one model call.

This is NOT the capability replaying from an artifact; the replay engine (§3.3)
does not exist. It is proof that the *mechanism* reaches the right answer:

    login            control map -> locate_control -> use_control
    overview         the same
    the balance      extract_panel: anchor on the table header, crop, one
                     model call against a response schema, select the row in
                     CODE by the parameter

Nothing is asked where account 13344's row is. The extract returns eleven rows
and the parameter picks one — which is the whole argument of issues 0009 / 0011.

The anchor is recorded from the COMMITTED discovery screenshot and matched
against a freshly loaded page, so this also exercises cross-session locator
stability rather than a self-match.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from interfaceai import parabank
from interfaceai.control_map_store import ControlMapMiss, ControlMapStore, MapKey
from interfaceai.decisions import ManualActionKind
from interfaceai.screenshot2controls import (
    ClickPoint,
    CropBox,
    ResolveInput,
    ScreenInput,
    _make_locator,
    locate_control,
)
from interfaceai.settings import get_settings
from interfaceai.surface import ActionPolicy, OffLoop, PlaywrightSurface, use_control
from interfaceai.table import Offset, extract_panel
from interfaceai.vision_llm import call_vision_llm

ROOT = Path(__file__).resolve().parents[1]
MAPS = ROOT / "control_maps"
RECORDED = ROOT / "evidence" / "runs" / "20260926T022551Z" / "frames" / "004-03-overview.png"

pytestmark = pytest.mark.live


class AccountRow(BaseModel):
    account_id: str
    balance: str


class AccountsTable(BaseModel):
    rows: list[AccountRow]


def _act(surface, control, action, value=None):
    """The replay chain: re-locate on the CURRENT screen, then act."""
    found = locate_control(
        ResolveInput(screenshot_png=surface.screenshot(), locator=control.locator)
    )
    assert found.status == "matched", f"{control.id}: {found.status} ({found.reason})"
    return use_control(
        surface,
        found.point.x,
        found.point.y,
        action,
        value,
        policy=ActionPolicy(
            allowed_actions=frozenset({ManualActionKind.CLICK, ManualActionKind.ENTER_TEXT})
        ),
    )


def test_read_the_savings_balance_of_account_13344() -> None:
    settings = get_settings()
    base = settings.parabank_base_url
    if not parabank.is_seeded(base):
        pytest.skip(f"{base} is not seeded; run `interfaceai env reset`")

    store = ControlMapStore(MAPS)
    index = MapKey(app="parabank", tenant="baseline", screen="index")
    try:
        store.get(index)
    except ControlMapMiss:
        pytest.skip("no control map for parabank/baseline/index; run discovery first")

    # The 'Account' column header: unique on the screen, unlike any of its
    # eleven rows. Recorded from the committed discovery screenshot, matched
    # against a freshly loaded page below.
    #
    # ⚠️ ONE column's header, not the header ROW. Table columns auto-size to
    # their content, so a patch spanning a column boundary moves when the row
    # count changes. Measured: a 3-column crop recorded on the seeded table
    # scores 0.0000 against the CLEAN table (1 row); this single-cell crop
    # scores 1.0000 on both.
    anchor = _make_locator(
        ScreenInput(screenshot_png=RECORDED.read_bytes()),
        CropBox(x=486, y=316, width=90, height=28),
        ClickPoint(x=490, y=320),
    )

    with PlaywrightSurface(allowed_origins=settings.allowed_origins) as surface, OffLoop() as off:
        surface.navigate(f"{base}/index.htm")
        _act(
            surface,
            store.control(index, "username_textbox"),
            ManualActionKind.ENTER_TEXT,
            settings.parabank_demo_username,
        )
        _act(
            surface,
            store.control(index, "password_textbox"),
            ManualActionKind.ENTER_TEXT,
            settings.parabank_demo_password.get_secret_value(),
        )
        _act(surface, store.control(index, "log_in_button"), ManualActionKind.CLICK)
        surface.wait(2.0)

        screenshot = surface.screenshot()
        read = off.run(
            extract_panel(
                screenshot,
                anchor,
                panel=Offset(dx=-20, dy=28, width=310, height=320),
                key_column=Offset(dx=0, dy=28, width=40, height=320),
                response_model=AccountsTable,
                vision=call_vision_llm,
                instruction=(
                    "This is a crop of an accounts table. Return every row: the "
                    "account number and its balance, exactly as printed."
                ),
            )
        )

    # The parameter selects the row. In code. No model asked where it is.
    wanted = str(parabank.DEMO_SAVINGS_ACCOUNT_ID)
    matches = [r for r in read.data.rows if r.account_id == wanted]
    assert len(matches) == 1, f"{wanted} appears {len(matches)}x in {read.data.rows}"

    balance = matches[0].balance.replace("$", "").replace(",", "")
    assert balance == f"{parabank.DEMO_SAVINGS_BALANCE:.2f}", (
        f"read {balance!r}, seed fixture says {parabank.DEMO_SAVINGS_BALANCE}"
    )

    # And drilldown, which cannot be reached without the extract above.
    index_of = [r.account_id for r in read.data.rows].index(wanted)
    point = read.point_for_row(index_of, x=508)
    assert 595 <= point.y <= 625, f"drilldown point y={point.y} is not on 13344's row"
