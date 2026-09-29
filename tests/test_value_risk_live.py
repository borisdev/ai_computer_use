"""A loan over the tenant's threshold stops and asks a person (assignment 3.4).

`live` — needs ParaBank up and seeded.

⚠️ **No loan is ever submitted.** Every test here uses an amount at or above the
threshold, so the run stops at the irreversible step and the fixtures stay
clean. That is not a limitation of the test; it is the feature.

The capability exists because nothing else in ParaBank has TWO money fields and
a genuinely irreversible submit. It is the smallest real thing the rule can be
demonstrated against.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from interfaceai import parabank
from interfaceai.capabilities import LIBRARY
from interfaceai.capability import approve, load_capability
from interfaceai.control_map_store import ControlMapStore
from interfaceai.outcomes import NeedsOperator, Success
from interfaceai.replay import replay
from interfaceai.settings import get_settings
from interfaceai.vision_llm import call_vision_llm

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "request_loan.v1.approved.json"

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def seeded():
    if not parabank.is_seeded():
        pytest.skip("ParaBank is not up; run `interfaceai env reset`")
    parabank.ParaBankAdmin().init_db()
    yield
    # ⚠️ RESEED AFTERWARDS TOO. Two tests here click the irreversible submit,
    # so the LAST one in the module left a real loan application in the live
    # database for whatever ran next -- the suite's seeded-state contract held
    # for every test except the one that broke it. Found by Copilot, PR #5.
    parabank.ParaBankAdmin().init_db()


def _run(
    amount: str,
    down_payment: str,
    *,
    threshold: str | None = "1000",
    confirm_risky: bool = False,
):
    settings = get_settings()
    from decimal import Decimal

    return replay(
        load_capability(ARTIFACT),
        {"amount": amount, "down_payment": down_payment},
        store=ControlMapStore(ROOT / "control_maps"),
        evidence_root=ROOT / "evidence" / "runs",
        secrets={
            "parabank_username": settings.parabank_demo_username,
            "parabank_demo_password": settings.parabank_demo_password.get_secret_value(),
        },
        vision=call_vision_llm,
        allowed_origins=settings.allowed_origins,
        confirm_money_above=Decimal(threshold) if threshold else None,
        confirm_risky=confirm_risky,
        library={n: approve(c, "test") for n, c in LIBRARY.items()},
    )


def test_a_loan_over_the_threshold_stops_and_names_the_amount() -> None:
    result = _run("1500", "200")
    assert isinstance(result, NeedsOperator), result
    assert "irreversible" in result.why
    assert "1500" in result.why and "1000" in result.why
    # It got all the way to the form before stopping -- the escalation is
    # "I could, and I should not without you", not "I could not".
    assert "enter down_payment_textbox" in result.completed_steps


def test_the_DOWN_PAYMENT_can_be_what_trips_it() -> None:
    """A loan form has two money fields and either one is enough."""
    result = _run("500", "2000")
    assert isinstance(result, NeedsOperator), result
    assert "down_payment=2000" in result.why


def test_under_the_threshold_it_is_only_the_CONTROL_that_stops_it() -> None:
    """Below the threshold the value rule is silent; `irreversible` still is not.

    Distinguishing the two messages matters: one says "this amount needs a
    look", the other says "this button always does".
    """
    result = _run("500", "50")
    assert isinstance(result, NeedsOperator), result
    assert "threshold" not in result.why
    assert "irreversible" in result.why


def test_the_threshold_is_the_tenants_and_a_lower_one_catches_the_same_loan() -> None:
    """§3.7: one institution's routine loan is another's exception."""
    lenient = _run("500", "50", threshold="1000")
    strict = _run("500", "50", threshold="250")
    assert "threshold" not in lenient.why
    assert "threshold" in strict.why
    assert "amount=500" in strict.why


def test_a_RUN_flag_cannot_answer_a_TENANT_policy() -> None:
    """`--confirm-risky` must not buy its way past the money threshold.

    ⚠️ REGRESSION. Both conditions used to sit in one `if`, so confirming
    irreversible steps skipped the value check entirely and this exact call
    replayed SUCCESS -- a $25,000 loan submitted with no human against a $1,000
    threshold. Measured against the live app on 2026-09-28.

    The two are different authorities. The flag is the CALLER saying "this run
    may do irreversible things". The threshold is the BANK saying "a person
    signs off above this amount" -- a question never addressed to the caller,
    so the caller's blanket yes cannot answer it.

    Note the level: `needs_human_confirmation` was correct throughout and a
    test of it passed the whole time the bypass existed. The defect was the
    branch, so the test has to run the branch.
    """
    result = _run("25000", "5000", confirm_risky=True)
    assert isinstance(result, NeedsOperator), result
    assert "threshold" in result.why
    assert "25000" in result.why


def test_confirming_still_lets_an_ORDINARY_loan_through() -> None:
    """The other direction, so the fix is not just a blanket refusal.

    A guard that stops everything passes the test above and is useless.
    """
    result = _run("500", "50", confirm_risky=True)
    assert isinstance(result, Success), result
