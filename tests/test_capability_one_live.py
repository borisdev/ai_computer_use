"""Capability 1 — the brief's worked example — replayed from an artifact.

`live` — needs ParaBank up and seeded, and spends one model call per run.

    "look up member 12345 and read their current savings balance"

This is the whole thread: an approved artifact, typed inputs, deterministic
replay, typed outputs. The accounts table is read ONCE as a
`TABLE_CONTROL_PANEL` and the caller's `account_id` selects a row **in code** --
nothing is asked where a row is, which is what keeps `docs/issues/0009`
(wrong-row grounding, 3 in 4, silently) off this path.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from interfaceai import parabank
from interfaceai.capabilities import LIBRARY
from interfaceai.capability import approve, load_capability
from interfaceai.control_map_store import ControlMapStore
from interfaceai.outcomes import (
    Failed,
    Success,
    is_actionable_by_caller,
)
from interfaceai.replay import replay
from interfaceai.settings import get_settings
from interfaceai.vision_llm import call_vision_llm

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "read_savings_balance.v3.approved.json"

pytestmark = pytest.mark.live


def _run(account_id: str):
    settings = get_settings()
    return replay(
        load_capability(ARTIFACT),
        {"account_id": account_id},
        store=ControlMapStore(ROOT / "control_maps"),
        evidence_root=ROOT / "evidence" / "runs",
        secrets={
            "parabank_username": settings.parabank_demo_username,
            "parabank_demo_password": settings.parabank_demo_password.get_secret_value(),
        },
        vision=call_vision_llm,
        allowed_origins=settings.allowed_origins,
        # Capability 1 invokes `log_in`, so the library must hold it approved.
        library={n: approve(c, "test") for n, c in LIBRARY.items()},
    )


@pytest.fixture(autouse=True)
def seeded():
    if not parabank.is_seeded():
        pytest.skip("ParaBank is not up; run `interfaceai env reset`")
    parabank.ParaBankAdmin().init_db()


def _money(text: str) -> Decimal:
    return Decimal(text.replace("$", "").replace(",", ""))


def test_the_assignments_own_example() -> None:
    result = _run(str(parabank.DEMO_SAVINGS_ACCOUNT_ID))
    assert isinstance(result, Success), result
    assert result.outputs["found_account_id"] == "13344"
    assert _money(result.outputs["balance"]) == parabank.DEMO_SAVINGS_BALANCE
    assert result.outputs["account_type"] == "SAVINGS"


def test_a_CHECKING_account_violates_the_savings_checkpoint() -> None:
    """The capability promises a SAVINGS balance. 12345 is CHECKING.

    No database manipulation — this is seeded data. The drilldown reaches the
    detail page by ARITHMETIC (row index from the panel read, y from the
    measured 28px rhythm), reads `Account Type`, and the checkpoint refuses.

    This is the check v2 could not make: it read the overview, which has no
    type column, so it would have returned a checking balance and called it a
    success.
    """
    checking = next(a for a in parabank.ACCOUNTS if a.type == "CHECKING")
    result = _run(str(checking.id))
    assert isinstance(result, Failed), result
    assert result.expected == "SAVINGS"
    assert result.observed == "CHECKING"
    assert not is_actionable_by_caller(result)


def test_a_changed_record_under_the_same_id_is_caught() -> None:
    """The failure this whole project exists to prevent.

    ParaBank's CLEAN state keeps account 13344 and changes what it IS --
    CHECKING $5,022.93 instead of SAVINGS $1,231.10. The id still resolves, so
    a checkpoint asserting "did I find 13344" passes and hands a bank the wrong
    number. This asserts the VALUE, and refuses.

    It also exercises the one-row path: CLEAN leaves a single account, so
    autocorrelation has no period to measure and the drilldown falls back to
    the pitch recorded when the panel was authored. That fallback is what makes
    the row reachable at all — without it this run stops at `NeedsOperator` and
    never learns the record changed.
    """
    parabank.ParaBankAdmin().clean_db()
    try:
        result = _run(str(parabank.DEMO_SAVINGS_ACCOUNT_ID))
    finally:
        parabank.ParaBankAdmin().init_db()

    assert isinstance(result, Failed), result
    assert result.expected == "SAVINGS"
    assert result.observed == "CHECKING"
    assert not is_actionable_by_caller(result)


def test_the_recorded_pitch_is_only_a_FALLBACK() -> None:
    """A live measurement must win, because a recorded one can go stale."""
    import json

    result = _run(str(parabank.DEMO_SAVINGS_ACCOUNT_ID))
    assert isinstance(result, Success), result
    assert result.evidence_dir is not None
    events = [
        json.loads(line) for line in (result.evidence_dir / "trace.jsonl").read_text().splitlines()
    ]
    assert not [e for e in events if e["event"] == "pitch_from_record"], (
        "the seeded table has 11 rows, so the pitch must be MEASURED, not recalled"
    )
    resolved = next(e for e in events if e["event"] == "row_resolved")
    assert resolved["pitch"] == 28
