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
    BusinessOutcome,
    BusinessOutcomeKind,
    Failed,
    NeedsOperator,
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


def test_a_one_row_table_refuses_the_drilldown_rather_than_guessing() -> None:
    """A documented limit, pinned.

    After `env break` only account 13344 remains, so the table has ONE row and
    autocorrelation has no period to find. The drilldown needs a row pitch to
    turn an index into a y, so it refuses — `NeedsOperator`, exit 1, no wrong
    answer. Reading a one-row table still works; only opening it does not.
    """
    parabank.ParaBankAdmin().clean_db()
    try:
        result = _run(str(parabank.DEMO_SAVINGS_ACCOUNT_ID))
    finally:
        parabank.ParaBankAdmin().init_db()
    assert isinstance(result, NeedsOperator), result
    assert "rhythm" in result.why
    assert not is_actionable_by_caller(result)


@pytest.mark.parametrize("account_id", ["12678"])
def test_the_same_artifact_answers_for_another_savings_account(account_id: str) -> None:
    """Parameterisation, against the seed fixtures.

    ⚠️ Only SAVINGS accounts, and that is the capability's contract rather than
    a convenience. v2 accepted any account because it read the overview, which
    has no type column. v3 drills in and checkpoints `account_type == SAVINGS`,
    so asking it for a checking account is a violated checkpoint — asserted
    directly in the test above.

    12678 is the other seeded savings account and its balance is **negative**
    (-$100.00), which is where a naive money parse falls over.
    """
    expected = next(a for a in parabank.ACCOUNTS if str(a.id) == account_id)
    assert expected.type == "SAVINGS"
    result = _run(account_id)
    assert isinstance(result, Success), result
    assert result.outputs["found_account_id"] == account_id
    assert _money(result.outputs["balance"]) == expected.balance
    assert result.outputs["account_type"] == "SAVINGS"


def test_an_account_that_does_not_exist_is_a_BUSINESS_OUTCOME() -> None:
    """The brief's glossary: conflating this with a crash is the common mistake.

    Account 99999 is in no seed row. The run is not broken -- it has an answer,
    and the answer is that there is no such record. `exit 0` from the CLI,
    because the caller can act on it.
    """
    result = _run(str(parabank.MISSING_ACCOUNT_ID))
    assert isinstance(result, BusinessOutcome), result
    assert result.kind is BusinessOutcomeKind.RECORD_NOT_FOUND
    assert "99999" in result.detail
    assert is_actionable_by_caller(result), "a business outcome is an ANSWER"


def test_the_balance_is_returned_and_never_asserted() -> None:
    """A capability that asserts its own answer returns a constant."""
    capability = load_capability(ARTIFACT)
    assert "balance" in {o.name for o in capability.returns}
    assert "balance" not in {c.output for c in capability.checkpoints}


def test_no_credential_is_persisted_in_the_run_evidence() -> None:
    """3.4, checked against what was actually written to disk."""
    settings = get_settings()
    password = settings.parabank_demo_password.get_secret_value()
    result = _run(str(parabank.DEMO_SAVINGS_ACCOUNT_ID))
    assert result.evidence_dir is not None
    trace = (result.evidence_dir / "trace.jsonl").read_text()
    assert password not in trace
    assert "value_length" in trace, "the length should be recorded even though the value is not"
