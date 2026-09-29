"""The vocabulary's only real requirement is that it does not move."""

from __future__ import annotations

import pytest

from interfaceai.vocabulary import VOCABULARY, VOCABULARY_VERSION, SlotType


def test_thirty_four_terms() -> None:
    """The count in docs/capabilities-and-vocabulary.md, so the doc goes stale loudly."""
    assert len(VOCABULARY.nouns) == 6
    assert len(VOCABULARY.verbs) == 7
    assert len(VOCABULARY.qualifiers) == 21
    assert len(VOCABULARY.terms) == 34


def test_every_term_is_unique() -> None:
    assert len(set(VOCABULARY.terms)) == len(VOCABULARY.terms)


def test_the_three_sensitive_slots() -> None:
    """Adding a fourth is a deliberate act, not a drive-by edit."""
    sensitive = {q.name for q in VOCABULARY.qualifiers if q.sensitive}
    assert sensitive == {"username", "password", "ssn"}


def test_account_id_is_a_string() -> None:
    """An identifier is never arithmetic, and a leading zero must survive."""
    assert VOCABULARY.qualifier("account_id").type is SlotType.STRING


def test_money_slots_are_typed_as_money() -> None:
    money = {q.name for q in VOCABULARY.qualifiers if q.type is SlotType.MONEY}
    assert money == {"balance", "amount", "down_payment"}


def test_an_unknown_term_raises_rather_than_returning_none() -> None:
    with pytest.raises(KeyError):
        VOCABULARY.qualifier("acct_no")


def test_the_prompt_block_carries_every_term() -> None:
    """The formatter carries every term.

    ⚠️ Its docstring used to claim "the inventory prompt and the artifact
    validator read one source", which this test does not check and which is
    not true: `discover.py` passes the block to `_DECIDE_PROMPT` only. The
    COARSE INVENTORY call -- the one that names the controls -- never sees it.
    Narrowed 2026-09-29 (Copilot, PR #5); the gap itself is real and recorded
    in docs/capabilities-and-vocabulary.md.
    """
    block = VOCABULARY.as_prompt_block()
    for term in VOCABULARY.terms:
        assert term in block


def test_the_vocabulary_reaches_the_DECIDE_prompt_and_not_the_inventory() -> None:
    """Pin the real state, so "wire it into inventory" is a visible change.

    A test asserting only that a formatter works says nothing about whether
    anyone calls it. This says which caller does.
    """
    import inspect

    from interfaceai import discover, screenshot2controls

    assert "as_prompt_block" in inspect.getsource(discover)
    assert "as_prompt_block" not in inspect.getsource(screenshot2controls), (
        "the inventory now consumes the vocabulary -- update "
        "docs/capabilities-and-vocabulary.md, this gap is closed"
    )


def test_the_version_is_the_one_the_module_publishes() -> None:
    assert VOCABULARY.version == VOCABULARY_VERSION
