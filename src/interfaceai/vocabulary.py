"""The controlled vocabulary: a FIXED set of concepts a control can be about.

Derived backwards from the five capabilities the system has to perform, not
from an inventory of the application -- `docs/capabilities-and-vocabulary.md`
has the derivation and the cross-check against ParaBank's own WADL (which
changed nothing, and is recorded there as a method not to repeat).

Two things depend on this module, and they pull in opposite directions:

  * `capability.py` types a capability's parameters against it, so a slot name
    in an artifact is checked rather than spelled freehand.
  * the coarse inventory prompt gets it verbatim, as one third of the fix for
    issue 0001 -- 15/24/22 controls from identical screenshot bytes, with six
    of eight varying entries being the same three unlabelled icons named two
    different ways. Giving the model a closed set to RESOLVE INTO removes the
    naming half of that churn.

**Its job is to be fixed, not to be complete.** A wrong-but-stable vocabulary
removes the variance; a perfect one regenerated each run does not. So it is a
module-level constant with a version, and a capability records which version it
was authored against -- v2 must not silently redefine a term a saved artifact
depends on.

`sensitive` is the flag that makes an artifact committable. A slot marked
sensitive can never carry a literal value (enforced in `capability.py`), so a
password reaches the page through an `input_ref` resolved at replay and never
lands in a file. Assignment 3.4.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from interfaceai.contracts import Contract

# Bump when a term is added, renamed or removed. Artifacts record the version
# they were authored against and refuse to replay under a different one.
VOCABULARY_VERSION = 1


class SlotType(StrEnum):
    """What a qualifier's value IS, so a parameter can be typed.

    Deliberately four. `account_id` is a STRING, not an integer: it is an
    identifier that is never arithmetic, and typing it as a number invites
    somebody to strip a leading zero on an application that has them.
    """

    STRING = "string"
    MONEY = "money"
    DATE = "date"
    INTEGER = "integer"


class Qualifier(Contract):
    """A typed slot a capability takes, returns, or fills a control with."""

    name: str = Field(min_length=1)
    type: SlotType
    # Never persisted in an artifact, never written to an evidence log.
    sensitive: bool = False


class ControlledVocabulary(Contract):
    """Nouns, verbs and qualifiers. 34 terms, small enough to put in a prompt."""

    version: int
    nouns: tuple[str, ...]
    verbs: tuple[str, ...]
    qualifiers: tuple[Qualifier, ...]

    def qualifier(self, name: str) -> Qualifier:
        for q in self.qualifiers:
            if q.name == name:
                return q
        raise KeyError(f"{name!r} is not in vocabulary v{self.version}")

    def has(self, name: str) -> bool:
        return any(q.name == name for q in self.qualifiers)

    @property
    def terms(self) -> tuple[str, ...]:
        return self.nouns + self.verbs + tuple(q.name for q in self.qualifiers)

    def as_prompt_block(self) -> str:
        """The vocabulary as the inventory prompt sees it.

        One place, so the prompt and the artifact validator cannot disagree
        about what a term is -- which is the drift the vocabulary exists to
        stop, reappearing one level up.
        """
        slots = ", ".join(q.name for q in self.qualifiers)
        return f"nouns: {', '.join(self.nouns)}\nverbs: {', '.join(self.verbs)}\nslots: {slots}"


VOCABULARY = ControlledVocabulary(
    version=VOCABULARY_VERSION,
    # What the work is about.
    nouns=("account", "customer", "transaction", "payee", "position", "loan"),
    # What is done to them. Domain verbs live in what people ask for, not in an
    # API spec -- only 2 of these 7 appear in ParaBank's WADL.
    verbs=("look_up", "transfer", "open", "update", "search", "confirm", "pay"),
    qualifiers=(
        Qualifier(name="account_id", type=SlotType.STRING),
        Qualifier(name="account_type", type=SlotType.STRING),
        Qualifier(name="balance", type=SlotType.MONEY),
        Qualifier(name="amount", type=SlotType.MONEY),
        Qualifier(name="from_account", type=SlotType.STRING),
        Qualifier(name="to_account", type=SlotType.STRING),
        Qualifier(name="from_date", type=SlotType.DATE),
        Qualifier(name="to_date", type=SlotType.DATE),
        # The three sensitive slots. They travel through controls exactly like
        # any other parameter; what differs is that an artifact may only hold a
        # reference to them, never the value.
        Qualifier(name="username", type=SlotType.STRING, sensitive=True),
        Qualifier(name="password", type=SlotType.STRING, sensitive=True),
        Qualifier(name="ssn", type=SlotType.STRING, sensitive=True),
        Qualifier(name="first_name", type=SlotType.STRING),
        Qualifier(name="last_name", type=SlotType.STRING),
        Qualifier(name="street", type=SlotType.STRING),
        Qualifier(name="city", type=SlotType.STRING),
        Qualifier(name="state", type=SlotType.STRING),
        Qualifier(name="zip_code", type=SlotType.STRING),
        Qualifier(name="phone_number", type=SlotType.STRING),
        Qualifier(name="transaction_id", type=SlotType.STRING),
        Qualifier(name="down_payment", type=SlotType.MONEY),
        Qualifier(name="payee_name", type=SlotType.STRING),
    ),
)
