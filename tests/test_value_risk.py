"""Risk that depends on the VALUE, not only on the control (assignment 3.4).

`ControlPolicy.irreversible` says *"this control moves money"*. This says
*"this amount is one a person should see"*. Two axes, and a bank needs both —
the handoff bundle named context-dependent risk as integration work left open.

Both end at the same enforcement point: `use_control` refuses a risky action
nobody confirmed, so there is still exactly one place that can act.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from interfaceai.decisions import ManualActionKind, needs_human_confirmation
from interfaceai.settings import Settings
from interfaceai.surface import ActionPolicy, NotAllowedError
from interfaceai.vocabulary import VOCABULARY, SlotType

ABOVE = Decimal(1000)


# --- what counts as needing a person ---------------------------------------


@pytest.mark.parametrize("amount", ["1000", "1000.00", "1500", "$1,500.00", "20000"])
def test_an_amount_at_or_above_the_threshold_needs_a_person(amount: str) -> None:
    reason = needs_human_confirmation("amount", amount, above=ABOVE)
    assert reason is not None
    assert "threshold" in reason


@pytest.mark.parametrize("amount", ["999.99", "500", "$50.00", "0", "0.01"])
def test_an_amount_below_it_does_not(amount: str) -> None:
    assert needs_human_confirmation("amount", amount, above=ABOVE) is None


def test_a_large_WITHDRAWAL_counts_too() -> None:
    """The magnitude is what matters; a sign does not make it safe."""
    assert needs_human_confirmation("amount", "-5000.00", above=ABOVE) is not None


# --- what does NOT trigger it, and why ------------------------------------


def test_an_account_number_is_not_an_amount() -> None:
    """13344 parses as a number and is not money.

    `account_id` is a STRING in the vocabulary precisely so identifiers are
    never arithmetic. The rule reads the slot's TYPE rather than guessing from
    the value.
    """
    assert VOCABULARY.qualifier("account_id").type is not SlotType.MONEY
    assert needs_human_confirmation("account_id", "13344", above=ABOVE) is None


def test_a_slot_outside_the_vocabulary_is_ignored() -> None:
    assert needs_human_confirmation("mystery", "99999", above=ABOVE) is None


def test_no_threshold_means_no_rule() -> None:
    assert needs_human_confirmation("amount", "999999", above=None) is None


def test_an_unreadable_money_value_needs_a_person_rather_than_passing() -> None:
    """A field the system cannot read is not a field it may call small."""
    reason = needs_human_confirmation("amount", "one thousand", above=ABOVE)
    assert reason is not None
    assert "cannot read" in reason


@pytest.mark.parametrize("slot", ["balance", "down_payment"])
def test_every_money_slot_is_covered_not_just_amount(slot: str) -> None:
    assert VOCABULARY.qualifier(slot).type is SlotType.MONEY
    assert needs_human_confirmation(slot, "5000", above=ABOVE) is not None


# --- per tenant (assignment 3.7) -------------------------------------------


def test_the_threshold_is_tenant_configuration() -> None:
    """One institution's routine transfer is another's exception."""
    settings = Settings(interfaceai_confirm_money_above="baseline=1000,feature=250")
    assert settings.confirm_money_above("baseline") == Decimal(1000)
    assert settings.confirm_money_above("feature") == Decimal(250)
    assert settings.confirm_money_above("unlisted") is None

    amount = "500.00"
    assert needs_human_confirmation("amount", amount, above=Decimal(1000)) is None
    assert needs_human_confirmation("amount", amount, above=Decimal(250)) is not None


def test_a_malformed_threshold_disables_the_rule_rather_than_crashing() -> None:
    settings = Settings(interfaceai_confirm_money_above="baseline=lots")
    assert settings.confirm_money_above("baseline") is None


# --- it ends at the same chokepoint ----------------------------------------


def test_enforcement_is_still_use_control_and_nothing_reaches_the_app() -> None:
    """The classification is new; the gate is the one that already existed."""
    policy = ActionPolicy(confirm_money_above=ABOVE)
    with pytest.raises(NotAllowedError, match="irreversible"):
        # `risky` is what the classification sets; `confirmed` is what a person
        # supplies. use_control refuses the pair, as it always has.
        from interfaceai.surface import use_control

        use_control(
            None,  # never reached: the risk check precedes any surface call
            1,
            1,
            ManualActionKind.ENTER_TEXT,
            "1500.00",
            policy=policy,
            risky=True,
            confirmed=False,
        )
