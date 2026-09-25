"""Offline checks on the ParaBank fixture table.

These assert the constants other code will treat as replay checkpoints are
internally consistent. They cannot tell us the constants match a running
container -- test_parabank_live.py does that.
"""

from decimal import Decimal

from interfaceai import parabank


def test_demo_savings_account_is_in_the_fixture_table() -> None:
    account = next(a for a in parabank.ACCOUNTS if a.id == parabank.DEMO_SAVINGS_ACCOUNT_ID)
    assert account.type == "SAVINGS"
    assert account.balance == parabank.DEMO_SAVINGS_BALANCE


def test_missing_account_id_is_actually_missing() -> None:
    assert all(a.id != parabank.MISSING_ACCOUNT_ID for a in parabank.ACCOUNTS)


def test_every_account_belongs_to_a_seeded_customer() -> None:
    customer_ids = {c.id for c in parabank.CUSTOMERS}
    assert all(a.customer_id in customer_ids for a in parabank.ACCOUNTS)


def test_account_ids_are_unique() -> None:
    ids = [a.id for a in parabank.ACCOUNTS]
    assert len(ids) == len(set(ids))


def test_demo_user_has_a_sub_minimum_account() -> None:
    """A transfer out of this one should trip ParaBank's own validation."""
    assert any(a.balance < Decimal(str(parabank.MINIMUM_BALANCE)) for a in parabank.ACCOUNTS)


def test_clean_state_reuses_a_seeded_account_id_with_different_data() -> None:
    """The point of the CLEAN lever: same id, different record.

    A replay that only checks "did I find account 13344" would pass in both
    states and hand back the wrong balance. The checkpoint has to assert the
    values, not the lookup.
    """
    clean = {a.id: a for a in parabank.CLEAN_STATE_ACCOUNTS}
    seeded = {a.id: a for a in parabank.ACCOUNTS}
    overlap = clean.keys() & seeded.keys()
    assert overlap, "CLEAN must leave at least one seeded id behind to be useful"
    for account_id in overlap:
        assert clean[account_id] != seeded[account_id]


def test_clean_state_removes_the_other_seeded_accounts() -> None:
    clean_ids = {a.id for a in parabank.CLEAN_STATE_ACCOUNTS}
    seeded_ids = {a.id for a in parabank.ACCOUNTS}
    assert seeded_ids - clean_ids, "CLEAN must drop some accounts, for the not-found branch"
