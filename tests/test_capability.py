"""The artifact's invariants, each one a failure that has already been measured.

Every refusal tested here corresponds to something in `docs/findings.md`:
a checkpoint that asserts a lookup passes on ParaBank's CLEAN state and returns
the wrong balance; a literal in a sensitive slot is a credential in git; a draft
reaching unattended replay is the approval gate being decoration.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from interfaceai import capabilities, parabank
from interfaceai.capability import (
    Approval,
    Capability,
    CapabilityError,
    Checkpoint,
    ControlRef,
    LiteralValue,
    OutputSpec,
    ParamSpec,
    ParamValue,
    SecretValue,
    Step,
    StepVerb,
    Target,
    UnapprovedError,
    approve,
    artifact_filename,
    assert_replayable,
    dump_capability,
    load_capability,
    validate_capability,
)
from interfaceai.vocabulary import VOCABULARY, VOCABULARY_VERSION

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"


def _capability(**overrides: object) -> Capability:
    """A minimal VALID capability, so each test breaks exactly one thing."""
    base: dict[str, object] = {
        "name": "probe",
        "version": 1,
        "goal": "a minimal capability used to test the validator",
        "vocabulary_version": VOCABULARY_VERSION,
        "target": Target(app="parabank", tenant="baseline", base_url="http://localhost:8080"),
        "viewport_width": 1280,
        "viewport_height": 900,
        "params": (ParamSpec(name="account_id", slot="account_id"),),
        "returns": (OutputSpec(name="found_account_id", slot="account_id"),),
        "steps": (
            Step(
                verb=StepVerb.EXTRACT,
                control=ControlRef(screen="activity", control_id="account_number_value"),
                slot="account_id",
                output="found_account_id",
                note="read the id back",
            ),
        ),
        "checkpoints": (
            Checkpoint(
                output="found_account_id",
                expected=ParamValue(param="account_id"),
                why="the record we asked for",
            ),
        ),
    }
    base.update(overrides)
    return Capability(**base)  # type: ignore[arg-type]


def test_the_probe_is_valid_so_every_other_test_breaks_one_thing() -> None:
    validate_capability(_capability())


# --- the authored registry -------------------------------------------------


def test_every_authored_capability_validates() -> None:
    capabilities.validate_all()


def test_capability_one_is_the_assignments_worked_example() -> None:
    c = capabilities.READ_SAVINGS_BALANCE
    assert [p.name for p in c.params] == ["account_id"]
    assert "balance" in {o.name for o in c.returns}


# --- sensitive slots: the committable-artifact guarantee -------------------


@pytest.mark.parametrize("slot", ["username", "password", "ssn"])
def test_a_sensitive_slot_cannot_hold_a_literal(slot: str) -> None:
    assert VOCABULARY.qualifier(slot).sensitive
    broken = _capability(
        steps=(
            Step(
                verb=StepVerb.ENTER,
                control=ControlRef(screen="index", control_id="x_textbox"),
                slot=slot,
                value=LiteralValue(value="hunter2"),
                note="a credential in a committed file",
            ),
            _capability().steps[0],
        )
    )
    with pytest.raises(CapabilityError, match="sensitive"):
        validate_capability(broken)


def test_a_sensitive_slot_cannot_be_a_caller_parameter_either() -> None:
    """A param is not persisted, but it is logged, echoed and passed around."""
    broken = _capability(
        params=(
            ParamSpec(name="account_id", slot="account_id"),
            ParamSpec(name="password", slot="password"),
        ),
        steps=(
            Step(
                verb=StepVerb.ENTER,
                control=ControlRef(screen="index", control_id="password_textbox"),
                slot="password",
                value=ParamValue(param="password"),
                note="still not an input_ref",
            ),
            _capability().steps[0],
        ),
    )
    with pytest.raises(CapabilityError, match="sensitive"):
        validate_capability(broken)


def test_a_sensitive_slot_accepts_an_input_ref() -> None:
    ok = _capability(
        steps=(
            Step(
                verb=StepVerb.ENTER,
                control=ControlRef(screen="index", control_id="password_textbox"),
                slot="password",
                value=SecretValue(input_ref="parabank_demo_password"),
                note="a key, not a credential",
            ),
            _capability().steps[0],
        )
    )
    validate_capability(ok)


# --- checkpoints assert values, never lookups ------------------------------


def test_a_checkpoint_must_name_a_declared_output() -> None:
    broken = _capability(
        checkpoints=(
            Checkpoint(
                output="on_screen_account_details",
                expected=LiteralValue(value="true"),
                why="this is a lookup wearing a checkpoint's clothes",
            ),
        )
    )
    with pytest.raises(CapabilityError, match="not a declared output"):
        validate_capability(broken)


def test_a_checkpoint_cannot_compare_against_a_secret() -> None:
    broken = _capability(
        checkpoints=(
            Checkpoint(
                output="found_account_id",
                expected=SecretValue(input_ref="parabank_demo_password"),
                why="would put a resolved secret into a comparison and a log",
            ),
        )
    )
    with pytest.raises(CapabilityError, match="cannot compare against a secret"):
        validate_capability(broken)


def test_capability_one_asserts_the_field_that_separates_the_two_db_states() -> None:
    """The self-check. Both numbers come from `parabank.py`, read off the app.

    After INIT, 13344 is SAVINGS $1,231.10. After CLEAN it is CHECKING
    $5,022.93 -- same id, different record. A checkpoint on the id alone passes
    in both, so this asserts that the capability checks the field that differs.
    """
    seeded = next(a for a in parabank.ACCOUNTS if a.id == parabank.DEMO_SAVINGS_ACCOUNT_ID)
    cleaned = next(
        a for a in parabank.CLEAN_STATE_ACCOUNTS if a.id == parabank.DEMO_SAVINGS_ACCOUNT_ID
    )
    assert seeded.type != cleaned.type, "the two states must differ, or this proves nothing"

    checkpoints = {c.output: c for c in capabilities.READ_SAVINGS_BALANCE.checkpoints}
    account_type = checkpoints["account_type"]
    assert isinstance(account_type.expected, LiteralValue)
    assert account_type.expected.value == seeded.type
    assert account_type.expected.value != cleaned.type


def test_balance_is_returned_and_never_asserted() -> None:
    """It is the answer. A capability that asserts its own answer returns a constant."""
    c = capabilities.READ_SAVINGS_BALANCE
    assert "balance" in {o.name for o in c.returns}
    assert "balance" not in {cp.output for cp in c.checkpoints}


# --- signature integrity ---------------------------------------------------


def test_a_declared_output_that_is_never_extracted_is_refused() -> None:
    broken = _capability(
        returns=(
            OutputSpec(name="found_account_id", slot="account_id"),
            OutputSpec(name="balance", slot="balance"),
        )
    )
    with pytest.raises(CapabilityError, match="never extracted"):
        validate_capability(broken)


def test_a_declared_parameter_that_nothing_reads_is_refused() -> None:
    """A signature that lies to its caller is worse than a missing one."""
    broken = _capability(
        params=(
            ParamSpec(name="account_id", slot="account_id"),
            ParamSpec(name="amount", slot="amount"),
        )
    )
    with pytest.raises(CapabilityError, match="never used"):
        validate_capability(broken)


def test_a_value_naming_no_parameter_is_refused() -> None:
    broken = _capability(
        checkpoints=(
            Checkpoint(
                output="found_account_id",
                expected=ParamValue(param="acct_id"),
                why="a typo the schema would otherwise carry into production",
            ),
        )
    )
    with pytest.raises(CapabilityError, match="no such parameter"):
        validate_capability(broken)


def test_a_slot_outside_the_vocabulary_is_refused() -> None:
    broken = _capability(returns=(OutputSpec(name="found_account_id", slot="acct_no"),))
    with pytest.raises(CapabilityError, match="not a vocabulary slot"):
        validate_capability(broken)


def test_extracting_the_same_output_twice_is_refused() -> None:
    step = _capability().steps[0]
    broken = _capability(steps=(step, step))
    with pytest.raises(CapabilityError, match="extracted twice"):
        validate_capability(broken)


def test_an_artifact_from_another_vocabulary_version_is_refused() -> None:
    broken = _capability(vocabulary_version=VOCABULARY_VERSION + 1)
    with pytest.raises(CapabilityError, match="vocabulary"):
        validate_capability(broken)


# --- step shape ------------------------------------------------------------


def test_click_does_not_take_a_value() -> None:
    with pytest.raises(ValueError, match="does not take a value"):
        Step(
            verb=StepVerb.CLICK,
            control=ControlRef(screen="index", control_id="log_in_button"),
            value=LiteralValue(value="x"),
            note="a click with text is a confused step",
        )


def test_enter_needs_a_value() -> None:
    with pytest.raises(ValueError, match="needs a value"):
        Step(
            verb=StepVerb.ENTER,
            control=ControlRef(screen="index", control_id="username_textbox"),
            note="nothing to type",
        )


def test_enter_needs_a_slot_saying_what_it_fills() -> None:
    """Without the slot there is no `sensitive` flag, so the guard cannot fire."""
    broken = _capability(
        steps=(
            Step(
                verb=StepVerb.ENTER,
                control=ControlRef(screen="index", control_id="username_textbox"),
                value=LiteralValue(value="john"),
                note="untyped",
            ),
            _capability().steps[0],
        )
    )
    with pytest.raises(CapabilityError, match="needs a slot"):
        validate_capability(broken)


def test_observe_takes_the_whole_screen() -> None:
    with pytest.raises(ValueError, match="whole screen"):
        Step(
            verb=StepVerb.OBSERVE,
            control=ControlRef(screen="activity", control_id="balance_value"),
            note="an observe of one control is an extract",
        )


def test_extract_needs_an_output_name() -> None:
    with pytest.raises(ValueError, match="needs an output name"):
        Step(
            verb=StepVerb.EXTRACT,
            control=ControlRef(screen="activity", control_id="balance_value"),
            note="read a value and drop it",
        )


# --- approval: the gate on unattended replay -------------------------------


def test_a_draft_cannot_be_replayed() -> None:
    with pytest.raises(UnapprovedError):
        assert_replayable(_capability())


def test_an_approved_capability_can_be_replayed() -> None:
    assert_replayable(approve(_capability(), "boris"))


def test_approval_must_be_attributed() -> None:
    with pytest.raises(CapabilityError, match="attributed"):
        approve(_capability(), "  ")


def test_an_approved_artifact_cannot_be_anonymous() -> None:
    with pytest.raises(ValueError, match="who approved it"):
        _capability(approval=Approval.APPROVED)


def test_a_draft_cannot_carry_an_approver() -> None:
    with pytest.raises(ValueError, match="draft cannot carry an approver"):
        _capability(approved_by="boris")


def test_approve_does_not_mutate_the_source() -> None:
    source = _capability()
    approve(source, "boris")
    assert source.approval is Approval.DRAFT


def test_replay_gate_also_runs_the_validator() -> None:
    """One gate, not two -- an approved but broken artifact must not pass."""
    broken = approve(_capability(vocabulary_version=VOCABULARY_VERSION + 1), "boris")
    with pytest.raises(CapabilityError):
        assert_replayable(broken)


# --- the committed artifacts ----------------------------------------------


@pytest.mark.parametrize("c", capabilities.REGISTRY, ids=lambda c: c.name)
def test_the_committed_draft_matches_the_authored_source(c: Capability) -> None:
    """Goes red when somebody edits the JSON instead of the source.

    `interfaceai capability export` regenerates it.
    """
    path = ARTIFACTS / artifact_filename(c)
    assert path.exists(), f"{path.name} is missing; run `interfaceai capability export`"
    assert path.read_text() == dump_capability(c)


@pytest.mark.parametrize("c", capabilities.REGISTRY, ids=lambda c: c.name)
def test_a_committed_artifact_round_trips(c: Capability) -> None:
    assert load_capability(ARTIFACTS / artifact_filename(c)) == c


def test_no_committed_artifact_carries_a_sensitive_value() -> None:
    """Read off the FILES, not the objects. A hand-edited artifact is the case.

    The validator already refuses this in memory; this asserts it about what is
    actually on disk and in git, which is the thing that could leak.
    """
    sensitive = {q.name for q in VOCABULARY.qualifiers if q.sensitive}
    files = sorted(ARTIFACTS.glob("*.json"))
    assert files, "no artifacts on disk: run `interfaceai capability export`"
    seen = 0
    for path in files:
        for step in json.loads(path.read_text())["steps"]:
            if step.get("slot") in sensitive:
                seen += 1
                assert step["value"]["kind"] == "secret", f"{path.name}: {step['slot']}"
    assert seen, "no sensitive slot appears in any artifact, so this asserted nothing"
