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
    """The inventory prompt and the artifact validator read one source."""
    block = VOCABULARY.as_prompt_block()
    for term in VOCABULARY.terms:
        assert term in block


def test_the_version_is_the_one_the_module_publishes() -> None:
    assert VOCABULARY.version == VOCABULARY_VERSION
