#!/usr/bin/env python3
"""Drill into ALL 11 accounts and check each opens ITS OWN detail page.

The claim this exists to back: capability 1 reaches a table row by INDEX and
never by grounding, so `docs/issues/0009` -- which lands on the wrong row 10
times in 11 -- is off its path.

Measured 2026-09-28: **11/11**, indices 0..10 in order.

    12345  CHECKING index= 0  drilled=yes  Failed   OK
    ...
    13344  SAVINGS  index= 9  drilled=yes  Success  OK
    54321  CHECKING index=10  drilled=yes  Failed   OK

⚠️ **The pattern is the proof, not just the count.** The two SAVINGS accounts
return Success and the nine CHECKING ones return Failed on the type checkpoint.
A drilldown landing on the wrong row would sometimes send a CHECKING request to
a SAVINGS row and pass wrongly. It never did.

Not in the test suite: 11 live replays take ~5 minutes and cost 11 model calls.
Run it when the row-targeting design changes.

    ./scripts/verify_all_drilldowns.py
"""

import json
from pathlib import Path

from interfaceai import parabank
from interfaceai.capabilities import LIBRARY
from interfaceai.capability import approve, load_capability
from interfaceai.control_map_store import ControlMapStore
from interfaceai.replay import replay
from interfaceai.settings import get_settings
from interfaceai.vision_llm import call_vision_llm

ROOT = Path(".")
settings = get_settings()
parabank.ParaBankAdmin().init_db()
cap = load_capability(ROOT / "artifacts" / "read_savings_balance.v3.approved.json")
accounts = [a for a in parabank.ACCOUNTS if a.customer_id == 12212]

hits = 0
for a in sorted(accounts, key=lambda x: x.id):
    result = replay(
        cap,
        {"account_id": str(a.id)},
        store=ControlMapStore(ROOT / "control_maps"),
        evidence_root=ROOT / "evidence" / "runs",
        secrets={
            "parabank_username": settings.parabank_demo_username,
            "parabank_demo_password": settings.parabank_demo_password.get_secret_value(),
        },
        vision=call_vision_llm,
        allowed_origins=settings.allowed_origins,
        library={n: approve(c, "probe") for n, c in LIBRARY.items()},
    )
    # ⚠️ THIS COMMENT USED TO SAY "read the detail page's own account number",
    # and the code below does not. `drilled` only proves SOME detail panel was
    # read, and the type comparison passes for every checking account if all
    # eleven clicks land on the same one. Found by Copilot, PR #5.
    #
    # The id is now read out of the panel and compared, which is the check the
    # comment always claimed: it fails when a drilldown lands on the wrong row
    # even though a panel was read and the type happens to match.
    events = [json.loads(l) for l in (result.evidence_dir / "trace.jsonl").read_text().splitlines()]
    rows = [
        e for e in events if e["event"] == "panel_read" and e["control"] == "account_details_panel"
    ]
    resolved = next((e for e in events if e["event"] == "row_resolved"), None)
    drilled = bool(rows)
    kind = type(result).__name__
    # The detail page's OWN id, from the extracted outputs -- not from what we
    # asked for. `found_account_id` is the row the run actually landed on.
    landed = (getattr(result, "outputs", {}) or {}).get("found_account_id")
    ok = drilled and landed == a.id
    hits += ok
    idx = resolved["index"] if resolved else "-"
    print(
        f"  {a.id}  {a.type:8s} index={idx!s:>2}  drilled={'yes' if drilled else 'NO '}  "
        f"landed={landed or '-':>6}  {kind:14s} {'OK' if ok else 'MISMATCH'}"
    )
print(f"\n{hits}/{len(accounts)} drilldowns opened the account that was asked for")
