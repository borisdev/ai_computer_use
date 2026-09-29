"""Risk that depends on the VALUE, not only on the control (assignment 3.4).

`ControlPolicy.irreversible` says *"this control moves money"*. This says
*"and this much of it"*. Two axes, and a bank needs both — the handoff bundle
named context-dependent risk as integration work left open.

⛔ **Checked at the irreversible action, not at the keystroke.** The first cut
fired when the amount was TYPED, which is wrong twice: nothing has moved yet,
and ParaBank's *Find Transactions* page has an `amount` field too — so
searching for £1,500 would have been blocked as if it moved money. The
vocabulary has one `amount` term and cannot tell the two apart. The **control**
can: only an irreversible one moves anything.

That is also how a bank behaves — you confirm at submit, not while typing.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from interfaceai.decisions import (
    UNREADABLE,
    ManualActionKind,
    money_entered,
    needs_human_confirmation,
)
from interfaceai.settings import Settings
from interfaceai.surface import ActionPolicy, NotAllowedError, use_control
from interfaceai.vocabulary import VOCABULARY, SlotType

ABOVE = Decimal(1000)


# --- what lands on the form ------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1500", Decimal(1500)), ("$1,500.00", Decimal("1500.00")), ("-5000", Decimal(-5000))],
)
def test_a_money_field_is_recorded(value: str, expected: Decimal) -> None:
    assert money_entered("amount", value) == expected


def test_an_account_number_is_not_an_amount() -> None:
    """13344 parses as a number and is not money.

    `account_id` is a STRING in the vocabulary precisely so identifiers are
    never arithmetic. The rule reads the slot's TYPE rather than guessing from
    the value.
    """
    assert VOCABULARY.qualifier("account_id").type is not SlotType.MONEY
    assert money_entered("account_id", "13344") is None


@pytest.mark.parametrize("slot", ["balance", "down_payment"])
def test_every_money_slot_counts_not_just_amount(slot: str) -> None:
    assert VOCABULARY.qualifier(slot).type is SlotType.MONEY
    assert money_entered(slot, "5000") == Decimal(5000)


def test_an_unreadable_money_value_is_recorded_as_unreadable_not_absent() -> None:
    """Absent is safe; unreadable is not, and they must not look the same."""
    assert money_entered("amount", "one thousand") is UNREADABLE


# --- what needs a person, at the irreversible step -------------------------


def test_an_amount_at_or_above_the_threshold_needs_a_person() -> None:
    reason = needs_human_confirmation({"amount": Decimal(1500)}, above=ABOVE)
    assert reason is not None
    assert "irreversible" in reason and "1500" in reason


def test_an_amount_below_it_does_not() -> None:
    assert needs_human_confirmation({"amount": Decimal("999.99")}, above=ABOVE) is None


def test_a_large_WITHDRAWAL_counts_too() -> None:
    """Magnitude decides; a sign does not make it safe."""
    assert needs_human_confirmation({"amount": Decimal(-5000)}, above=ABOVE) is not None


def test_any_ONE_field_over_the_threshold_is_enough() -> None:
    """A loan form has both an amount and a down payment."""
    entered = {"amount": Decimal(500), "down_payment": Decimal(2000)}
    reason = needs_human_confirmation(entered, above=ABOVE)
    assert reason is not None
    assert "down_payment" in reason
    assert "amount=500" not in reason, "only the fields that tripped it are named"


def test_an_unreadable_value_needs_a_person_rather_than_passing() -> None:
    reason = needs_human_confirmation({"amount": UNREADABLE}, above=ABOVE)
    assert reason is not None
    assert "cannot read" in reason


def test_nothing_typed_means_nothing_to_judge() -> None:
    """An irreversible step with no money on the form is still irreversible,
    but that is the CONTROL's risk, reported by the caller — not this rule."""
    assert needs_human_confirmation({}, above=ABOVE) is None


def test_no_threshold_means_no_rule() -> None:
    assert needs_human_confirmation({"amount": Decimal(999999)}, above=None) is None


# --- per tenant (assignment 3.7) -------------------------------------------


def test_the_threshold_is_tenant_configuration() -> None:
    """One institution's routine transfer is another's exception."""
    settings = Settings(interfaceai_confirm_money_above="baseline=1000,feature=250")
    assert settings.confirm_money_above("baseline") == Decimal(1000)
    assert settings.confirm_money_above("feature") == Decimal(250)
    assert settings.confirm_money_above("unlisted") is None

    five_hundred = {"amount": Decimal(500)}
    assert needs_human_confirmation(five_hundred, above=Decimal(1000)) is None
    assert needs_human_confirmation(five_hundred, above=Decimal(250)) is not None


def test_a_malformed_threshold_is_REFUSED_not_quietly_disabled() -> None:
    """⚠️ THIS TEST USED TO ASSERT THE BUG, under a reassuring name.

    It was `test_a_malformed_threshold_disables_the_rule_rather_than_crashing`
    and it pinned exactly the behaviour Copilot flagged on PR #5: a typo such
    as `baseline=lots` returned None, so the money guardrail silently did
    nothing while the config file still looked like it had one.

    "Rather than crashing" was the whole mistake. A money guardrail that cannot
    parse its own threshold has no safe default -- refusing to start is the
    quiet failure's only honest alternative.
    """
    with pytest.raises(ValueError, match="not a number"):
        Settings(interfaceai_confirm_money_above="baseline=lots").confirm_money_above("baseline")


def test_a_negative_or_infinite_threshold_is_refused_too() -> None:
    """`Decimal` accepts both, and neither can gate anything."""
    for bad in ("baseline=-5", "baseline=Infinity", "baseline=NaN"):
        with pytest.raises(ValueError):
            Settings(interfaceai_confirm_money_above=bad).confirm_money_above("baseline")


# --- it ends at the same chokepoint ----------------------------------------


def test_enforcement_is_still_use_control() -> None:
    """The classification is new; the gate is the one that already existed."""
    with pytest.raises(NotAllowedError, match="irreversible"):
        use_control(
            None,  # never reached: the risk check precedes any surface call
            1,
            1,
            ManualActionKind.CLICK,
            None,
            policy=ActionPolicy(),
            risky=True,
            confirmed=False,
        )


def test_money_on_form_is_NEVER_cleared_during_a_run() -> None:
    """The multi-page bypass, pinned at the only level that can catch it.

    A two-step flow -- enter $25,000 on page 1, submit on page 2 -- used to
    clear `money_on_form` on the URL change and judge the submit against an
    empty form, gated by `--confirm-risky` alone. That is the bypass fixed one
    commit earlier, one page further along. Found by `evals/grade.py` reading
    the clearing rule against the claim it was supporting.

    ⚠️ THIS IS A SOURCE-LEVEL CHECK AND IT IS THE HONEST ONE AVAILABLE.
    A behavioural test needs a live multi-page money flow and ParaBank's loan
    form is a single page -- which is exactly why the bug was latent and why
    no existing test caught it. Asserting on `needs_human_confirmation` would
    pass either way: that function was correct throughout, the CLEARING was
    the defect. So this pins the decision where it lives, and goes red the
    moment someone reintroduces the clear for the third time.
    """
    src = (Path(__file__).resolve().parents[1] / "src" / "interfaceai" / "replay.py").read_text()
    offenders = [
        line.strip() for line in src.splitlines() if "money_on_form" in line and ".clear()" in line
    ]
    assert not offenders, (
        "money_on_form is cleared during a run: " + "; ".join(offenders) + ". "
        "An amount entered on page 1 and submitted on page 2 would then be judged "
        "against an empty form. Over-escalating is the safe direction here."
    )
