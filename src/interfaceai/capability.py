"""The capability artifact: what discovery emits and replay executes.

Assignment 3.2 -- "a reusable, reviewable, parameterized capability an AI agent
can call, with typed input parameters". This module is the type; it does not
run anything.

    goal        natural language, input to DISCOVERY, once
                "log in as john and read the balance of savings account 13344"
    capability  typed artifact, invoked at REPLAY, many times
                read_savings_balance(account_id: str) -> balance: Money

Four decisions are baked into the shape here rather than left to a convention,
because each of them was already measured failing:

1.  **No coordinates, and no locators either.** A step names a control by
    `(screen, control_id)`; the pixel template that finds it lives in a
    per-tenant control map. Raw `(x, y)` scored 1/10 clicks inside the control
    (`docs/findings.md` S2), and a template is the least portable thing in the
    system -- keeping it out of the artifact is what lets one artifact serve
    two tenants whose CSS differs (S3.7).

2.  **A checkpoint asserts an extracted VALUE, never a lookup.** `Checkpoint`
    can only reference a declared output, so "did I reach account 13344" is not
    expressible. ParaBank's own CLEAN state is why: 13344 still resolves, as
    CHECKING $5,022.93 instead of SAVINGS $1,231.10. A presence checkpoint
    passes there and hands a bank a different record under the same id.

3.  **A sensitive slot cannot hold a literal.** `username`, `password` and
    `ssn` are marked sensitive in the vocabulary, and validation refuses an
    artifact that gives one a literal value. That is the difference between an
    artifact you can commit and one you cannot (S3.4).

4.  **Replay is gated on `approved`.** S8 -- "gate unattended replay on an
    approval state (draft -> approved)". Discovery emits `draft`; a human
    promotes it. `assert_replayable` is the single gate, so there is one place
    to route around and it is tested.

Three of the eight step verbs in `docs/capabilities-and-vocabulary.md` are
absent from `StepVerb`, on purpose:

    require   a capability-level precondition, re-checked on resume -- so it is
              `Capability.requires`, not a position in the step list
    assert    a checkpoint, for the same reason -- `Capability.checkpoints`
    escalate  not something an author writes. It is what the executor DOES when
              a step fails or when `Step.risky` is unconfirmed, so its authored
              form is the `risky` flag (S3.6).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from interfaceai.contracts import Contract
from interfaceai.surface import Viewport
from interfaceai.vocabulary import VOCABULARY, ControlledVocabulary, SlotType

# ---------------------------------------------------------------------------
# Values: where a step's text comes from
# ---------------------------------------------------------------------------


class LiteralValue(Contract):
    """A constant recorded at discovery. Never legal for a sensitive slot."""

    kind: Literal["literal"] = "literal"
    value: str


class ParamValue(Contract):
    """Bound at invocation from the caller's typed arguments.

    This is the half of parameterisation that is ours: discovery has to
    recognise that `13344` in a goal is a parameter rather than bake it in.
    The agent-facing product extracts the argument; we extract the signature.
    """

    kind: Literal["param"] = "param"
    param: str = Field(min_length=1)


class SecretValue(Contract):
    """A NAME resolved at replay from a secret provider. The value never lands here.

    `input_ref` is a key, not a credential -- `parabank_demo_password`, not
    `demo`. Persisting the value is what S3.4 forbids, and what makes the
    difference between an artifact that can live in git and one that cannot.
    """

    kind: Literal["secret"] = "secret"
    input_ref: str = Field(min_length=1)


Value = Annotated[LiteralValue | ParamValue | SecretValue, Field(discriminator="kind")]


# ---------------------------------------------------------------------------
# Controls: named, not located
# ---------------------------------------------------------------------------


class ControlRef(Contract):
    """Which control, by name, on which recorded screen.

    Resolved at replay through the control map for the tenant in hand, and from
    there through `locate_control`. The artifact stays tenant-agnostic; only
    the locator payload behind this name is tenant-specific.
    """

    screen: str = Field(min_length=1)
    control_id: str = Field(min_length=1)

    # For one-of-many rows: "the account link whose text is <account_id>".
    # The accounts overview has 11 near-identical rows, which `locate_control`
    # correctly reports as `ambiguous` rather than guessing. This field is how
    # a capability says WHICH one; the mechanism that honours it is not built
    # yet (docs/issues/0001). An artifact that could not express this could not
    # express capability 1 at all, which is why the field exists before the
    # code that reads it.
    discriminator: Value | None = None


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


class StepVerb(StrEnum):
    ENTER = "enter"
    CLICK = "click"
    SELECT = "select"
    WAIT_FOR = "wait_for"
    OBSERVE = "observe"
    EXTRACT = "extract"


_NEEDS_CONTROL = frozenset(
    {StepVerb.ENTER, StepVerb.CLICK, StepVerb.SELECT, StepVerb.WAIT_FOR, StepVerb.EXTRACT}
)
_NEEDS_VALUE = frozenset({StepVerb.ENTER, StepVerb.SELECT})


class Step(Contract):
    verb: StepVerb
    control: ControlRef | None = None
    value: Value | None = None
    # Which vocabulary qualifier this control is about. Carries the `sensitive`
    # flag that decides whether `value` may be a literal.
    slot: str | None = None
    # EXTRACT only: names a declared output.
    output: str | None = None
    # Irreversible. Flows to `use_control(risky=...)`, which refuses unless
    # something upstream confirmed. Risk is a property of the CONTROL -- "Log
    # In" and "Transfer" are both a CLICK -- so it is authored per step and
    # never inferred from the verb.
    risky: bool = False
    # For the human reviewing the draft. An artifact nobody can read is not
    # reviewable, and reviewable is the word the assignment uses.
    note: str = Field(min_length=1)

    @model_validator(mode="after")
    def _shape_matches_verb(self) -> Step:
        if self.verb in _NEEDS_CONTROL and self.control is None:
            raise ValueError(f"{self.verb} needs a control")
        if self.verb is StepVerb.OBSERVE and self.control is not None:
            raise ValueError("observe takes the whole screen, not a control")
        if self.verb in _NEEDS_VALUE and self.value is None:
            raise ValueError(f"{self.verb} needs a value")
        if self.verb not in _NEEDS_VALUE and self.value is not None:
            raise ValueError(f"{self.verb} does not take a value")
        if self.verb is StepVerb.EXTRACT and self.output is None:
            raise ValueError("extract needs an output name")
        if self.verb is not StepVerb.EXTRACT and self.output is not None:
            raise ValueError(f"{self.verb} does not produce an output")
        return self


# ---------------------------------------------------------------------------
# Preconditions and checkpoints
# ---------------------------------------------------------------------------


class Precondition(Contract):
    """Checked before the first step, and again after a human handoff.

    A precondition is a VISUAL question -- is this control on the screen --
    which `locate_control` answers with no model and no DOM. `authenticated`
    is "the log out link is present", and that is the honest answer to
    logged-out `overview.htm` returning HTTP 200 with an empty table: a
    checkpoint cannot catch that, a precondition can.

    It is also what makes resume safe. The operator may have logged out or
    navigated anywhere, so resume is never "continue from line N" -- it
    re-observes and re-checks these first.
    """

    name: str = Field(min_length=1)
    control: ControlRef
    must: Literal["present", "absent"]
    why: str = Field(min_length=1)


class Comparison(StrEnum):
    EQUALS = "equals"


class Checkpoint(Contract):
    """Did the run reach the state it was recorded against.

    Deliberately can only compare a declared OUTPUT. See the module docstring:
    a checkpoint that asserts a lookup succeeded passes on ParaBank's CLEAN
    state and returns the wrong balance.
    """

    output: str = Field(min_length=1)
    op: Comparison = Comparison.EQUALS
    expected: Value
    why: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------


class ParamSpec(Contract):
    name: str = Field(min_length=1)
    slot: str = Field(min_length=1)
    required: bool = True


class OutputSpec(Contract):
    name: str = Field(min_length=1)
    slot: str = Field(min_length=1)


class Target(Contract):
    """What this was authored against. Not a URL to navigate to.

    `tenant` selects the control map at replay; a capability recorded on tenant
    A is the same capability on tenant B, with different pixels behind the
    same control names.
    """

    app: str = Field(min_length=1)
    tenant: str = Field(min_length=1)
    base_url: str = Field(min_length=1)


class Approval(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"


class UnapprovedError(RuntimeError):
    """Replay was attempted on an artifact no human has approved (S8)."""


class Capability(Contract):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1)
    version: int = Field(ge=1)
    # The natural-language goal this was discovered from. Kept because it is
    # what a reviewer compares the steps against.
    goal: str = Field(min_length=1)
    vocabulary_version: int
    target: Target
    # Coordinates only mean anything relative to a viewport, so it is part of
    # the contract rather than a runtime detail.
    viewport_width: int = Field(gt=0)
    viewport_height: int = Field(gt=0)

    params: tuple[ParamSpec, ...] = ()
    returns: tuple[OutputSpec, ...] = ()
    requires: tuple[Precondition, ...] = ()
    steps: tuple[Step, ...] = Field(min_length=1)
    checkpoints: tuple[Checkpoint, ...] = Field(min_length=1)

    approval: Approval = Approval.DRAFT
    approved_by: str | None = None

    @model_validator(mode="after")
    def _approval_is_attributed(self) -> Capability:
        if self.approval is Approval.APPROVED and not self.approved_by:
            raise ValueError("an approved capability must record who approved it")
        if self.approval is Approval.DRAFT and self.approved_by:
            raise ValueError("a draft cannot carry an approver")
        return self

    @property
    def viewport(self) -> Viewport:
        return Viewport(width=self.viewport_width, height=self.viewport_height)


# ---------------------------------------------------------------------------
# Validation against the vocabulary
# ---------------------------------------------------------------------------


class CapabilityError(ValueError):
    """The artifact is internally inconsistent, or disagrees with the vocabulary."""


def validate_capability(
    capability: Capability,
    vocabulary: ControlledVocabulary | None = None,
) -> None:
    """Everything a pydantic field constraint cannot say. Raises on the first fault.

    Kept as a function rather than a `model_validator` so an artifact can be
    LOADED under a vocabulary it does not match and the mismatch reported,
    rather than the file becoming unreadable.
    """
    vocab = vocabulary or VOCABULARY

    if capability.vocabulary_version != vocab.version:
        raise CapabilityError(
            f"{capability.name} was authored against vocabulary "
            f"v{capability.vocabulary_version}; this is v{vocab.version}"
        )

    param_names = {p.name for p in capability.params}
    if len(param_names) != len(capability.params):
        raise CapabilityError("duplicate parameter name")
    output_names = {o.name for o in capability.returns}
    if len(output_names) != len(capability.returns):
        raise CapabilityError("duplicate output name")

    for spec in (*capability.params, *capability.returns):
        if not vocab.has(spec.slot):
            raise CapabilityError(f"{spec.name}: {spec.slot!r} is not a vocabulary slot")

    def check_value(value: Value | None, where: str, slot: str | None) -> None:
        if value is None:
            return
        if isinstance(value, ParamValue) and value.param not in param_names:
            raise CapabilityError(f"{where}: no such parameter {value.param!r}")
        if slot is None:
            return
        if not vocab.has(slot):
            raise CapabilityError(f"{where}: {slot!r} is not a vocabulary slot")
        if vocab.qualifier(slot).sensitive and not isinstance(value, SecretValue):
            raise CapabilityError(
                f"{where}: {slot!r} is sensitive, so it needs an input_ref, "
                f"not a {value.kind} value"
            )

    produced: set[str] = set()
    used_params: set[str] = set()
    for n, step in enumerate(capability.steps):
        where = f"step {n} ({step.verb})"
        if step.slot is not None and not vocab.has(step.slot):
            raise CapabilityError(f"{where}: {step.slot!r} is not a vocabulary slot")
        if step.verb in _NEEDS_VALUE and step.slot is None:
            raise CapabilityError(f"{where}: needs a slot saying what it is filling in")
        check_value(step.value, where, step.slot)
        if step.control is not None:
            check_value(step.control.discriminator, f"{where} discriminator", None)
            if isinstance(step.control.discriminator, ParamValue):
                used_params.add(step.control.discriminator.param)
        if isinstance(step.value, ParamValue):
            used_params.add(step.value.param)
        if step.output is not None:
            if step.output not in output_names:
                raise CapabilityError(f"{where}: {step.output!r} is not a declared output")
            if step.output in produced:
                raise CapabilityError(f"{where}: {step.output!r} is extracted twice")
            produced.add(step.output)

    missing = output_names - produced
    if missing:
        raise CapabilityError(f"declared but never extracted: {sorted(missing)}")

    for precondition in capability.requires:
        if precondition.control.discriminator is not None:
            check_value(
                precondition.control.discriminator,
                f"precondition {precondition.name}",
                None,
            )

    for checkpoint in capability.checkpoints:
        where = f"checkpoint on {checkpoint.output!r}"
        if checkpoint.output not in output_names:
            raise CapabilityError(f"{where}: not a declared output")
        check_value(checkpoint.expected, where, None)
        if isinstance(checkpoint.expected, SecretValue):
            raise CapabilityError(f"{where}: a checkpoint cannot compare against a secret")
        if isinstance(checkpoint.expected, ParamValue):
            used_params.add(checkpoint.expected.param)

    # A declared parameter nothing reads is a signature that lies to its caller.
    unused = param_names - used_params
    if unused:
        raise CapabilityError(f"declared but never used: {sorted(unused)}")


def assert_replayable(
    capability: Capability,
    vocabulary: ControlledVocabulary | None = None,
) -> None:
    """The single gate between an artifact and unattended execution.

    One function, so there is exactly one place to route around -- and a test
    asserting a draft cannot pass it.
    """
    validate_capability(capability, vocabulary)
    if capability.approval is not Approval.APPROVED:
        raise UnapprovedError(
            f"{capability.name} v{capability.version} is {capability.approval}; "
            "unattended replay needs a human approval"
        )


def slot_type(slot: str, vocabulary: ControlledVocabulary | None = None) -> SlotType:
    return (vocabulary or VOCABULARY).qualifier(slot).type


# ---------------------------------------------------------------------------
# On disk
# ---------------------------------------------------------------------------
#
# Two suffixes, because the approval state is the thing a reader most needs to
# see without opening the file:
#
#   <name>.v<n>.draft.json      exported from the authored source. Committed.
#   <name>.v<n>.approved.json   a human promoted it. `approved_by` says who.
#
# Export is deterministic (sorted keys, trailing newline) so a committed draft
# and a re-export compare byte for byte -- a test that goes red when somebody
# edits the JSON by hand instead of the source.


def artifact_filename(capability: Capability) -> str:
    return f"{capability.name}.v{capability.version}.{capability.approval.value}.json"


def dump_capability(capability: Capability) -> str:
    return capability.model_dump_json(indent=2) + "\n"


def load_capability(
    path: Path,
    vocabulary: ControlledVocabulary | None = None,
) -> Capability:
    """Read an artifact and check it against the vocabulary in force."""
    capability = Capability.model_validate_json(path.read_text())
    validate_capability(capability, vocabulary)
    return capability


def approve(capability: Capability, by: str) -> Capability:
    """The human action S8 asks for. Returns a new artifact; never mutates."""
    if not by.strip():
        raise CapabilityError("approval must be attributed to a person")
    return capability.model_copy(update={"approval": Approval.APPROVED, "approved_by": by})
