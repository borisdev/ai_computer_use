"""The artifact's invariants, each one a failure that has already been measured.

Every refusal tested here corresponds to something in `docs/findings.md`:
a checkpoint that asserts a lookup passes on ParaBank's CLEAN state and returns
the wrong balance; a literal in a sensitive slot is a credential in git; a draft
reaching unattended replay is the approval gate being decoration.
"""

from __future__ import annotations

import json
import re
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
    resolve_artifact,
    validate_capability,
    validate_invocations,
)
from interfaceai.vocabulary import VOCABULARY, VOCABULARY_VERSION

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"


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


def test_capability_one_checkpoints_the_field_that_separates_the_two_db_states() -> None:
    """The strong checkpoint, restored in v3 and pinned here.

    The history is the lesson. v1 drilled into `activity.htm` by GROUNDING the
    account's row link -- which lands on the wrong row 3 times in 4, silently
    (`docs/issues/0009`). v2 dropped the drilldown and with it this checkpoint,
    so it reported the balance of whatever 13344 had become. v3 drills in by
    ARITHMETIC: the row index comes from the panel read, the y from the measured
    28px rhythm, and no model is asked where a row is.

    The previous version of this test asserted the LOSS and told whoever
    restored the drilldown to come here. That is what happened.
    """
    seeded = next(a for a in parabank.ACCOUNTS if a.id == parabank.DEMO_SAVINGS_ACCOUNT_ID)
    cleaned = next(
        a for a in parabank.CLEAN_STATE_ACCOUNTS if a.id == parabank.DEMO_SAVINGS_ACCOUNT_ID
    )
    assert seeded.type != cleaned.type, "the two states must differ, or this proves nothing"

    checkpoints = {c.output: c for c in capabilities.READ_SAVINGS_BALANCE.checkpoints}
    assert "found_account_id" in checkpoints, "must prove it answered about the right record"

    account_type = checkpoints["account_type"]
    assert isinstance(account_type.expected, LiteralValue)
    assert account_type.expected.value == seeded.type
    assert account_type.expected.value != cleaned.type, (
        "the checkpoint must assert the value that DIFFERS between the two states"
    )


def test_the_drilldown_goes_through_a_row_key_not_a_grounded_row() -> None:
    """`docs/issues/0009` stays off this capability's path, by construction."""
    clicks = [
        s
        for s in capabilities.READ_SAVINGS_BALANCE.steps
        if s.verb is StepVerb.CLICK and s.control is not None
    ]
    assert clicks, "v3 drills into the account's row"
    for step in clicks:
        assert step.row_key is not None, (
            f"{step.control.control_id} is clicked without a row_key -- that is a "
            "grounded row, which is the defect this design removes"
        )


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
            if step.get("slot") not in sensitive:
                continue
            seen += 1
            # Reading one back out is refused outright -- see the EXTRACT rule
            # in `assert_replayable`. This asserted `value["kind"]` blindly and
            # so CRASHED on an extract step rather than reporting it, which is
            # how a real hole in the schema surfaced as a TypeError.
            assert step["verb"] != "extract", (
                f"{path.name}: extracts into the sensitive slot {step['slot']!r}"
            )
            assert step["value"]["kind"] == "secret", f"{path.name}: {step['slot']}"
    assert seen, "no sensitive slot appears in any artifact, so this asserted nothing"


# --- composition: a capability that calls another --------------------------


def _library(**extra: Capability) -> dict[str, Capability]:
    base = {c.name: approve(c, "test") for c in capabilities.REGISTRY}
    base.update({k: v for k, v in extra.items()})
    return base


def test_capability_one_invokes_log_in_rather_than_copying_it() -> None:
    """The point of a vocabulary: a small canonical set composes."""
    invokes = [s for s in capabilities.READ_SAVINGS_BALANCE.steps if s.verb is StepVerb.INVOKE]
    assert len(invokes) == 1
    assert invokes[0].invokes == "log_in"
    assert invokes[0].invokes_version == capabilities.LOG_IN.version


def test_every_authored_invocation_resolves() -> None:
    library = _library()
    for c in capabilities.REGISTRY:
        validate_invocations(approve(c, "test"), library)


def test_an_invoke_pins_the_version_and_refuses_a_drifted_library() -> None:
    """A capability that silently picked up a new dependency is not deterministic."""
    newer = capabilities.LOG_IN.model_copy(update={"version": 99})
    with pytest.raises(CapabilityError, match="pinned to v"):
        validate_invocations(
            approve(capabilities.READ_SAVINGS_BALANCE, "test"), _library(log_in=approve(newer, "t"))
        )


def test_an_unapproved_capability_cannot_be_smuggled_in_by_an_approved_one() -> None:
    library = _library()
    library["log_in"] = capabilities.LOG_IN  # draft
    with pytest.raises(CapabilityError, match="is draft"):
        validate_invocations(approve(capabilities.READ_SAVINGS_BALANCE, "test"), library)


def test_a_missing_capability_is_named_along_with_what_is_available() -> None:
    with pytest.raises(CapabilityError, match="no such capability"):
        validate_invocations(approve(capabilities.READ_SAVINGS_BALANCE, "test"), {})


def test_self_invocation_is_refused_at_authoring_time() -> None:
    broken = _capability(
        steps=(
            Step(verb=StepVerb.INVOKE, invokes="probe", invokes_version=1, note="itself"),
            _capability().steps[0],
        )
    )
    with pytest.raises(CapabilityError, match="cannot invoke itself"):
        validate_capability(broken)


def test_a_cycle_between_two_capabilities_is_refused() -> None:
    """Detected on the recursion, not by inspecting one artifact in isolation.

    Parameter-free on purpose: with a required param the bind check fires one
    level earlier and the test would pass for the wrong reason.
    """

    def shell(name: str, calls: str) -> Capability:
        return approve(
            _capability(
                name=name,
                params=(),
                returns=(),
                checkpoints=(),
                steps=(
                    Step(
                        verb=StepVerb.INVOKE,
                        invokes=calls,
                        invokes_version=1,
                        note=f"{name} -> {calls}",
                    ),
                    Step(verb=StepVerb.OBSERVE, note="evidence"),
                ),
            ),
            "test",
        )

    alpha, beta = shell("alpha", "beta"), shell("beta", "alpha")
    with pytest.raises(CapabilityError, match="cycle"):
        validate_invocations(alpha, {"alpha": alpha, "beta": beta})


def test_an_invoke_must_bind_the_required_parameters() -> None:
    child = approve(_capability(name="child"), "test")
    parent = approve(
        _capability(
            name="parent",
            returns=(),
            checkpoints=(),
            steps=(Step(verb=StepVerb.INVOKE, invokes="child", invokes_version=1, note="no bind"),),
            params=(),
        ),
        "test",
    )
    with pytest.raises(CapabilityError, match="does not bind"):
        validate_invocations(parent, {"parent": parent, "child": child})


def test_a_capability_that_returns_nothing_needs_no_checkpoint() -> None:
    """`log_in` is exactly this: reaching the authenticated nav is the condition,
    and its final wait_for already asserts it."""
    assert capabilities.LOG_IN.returns == ()
    assert capabilities.LOG_IN.checkpoints == ()
    validate_capability(capabilities.LOG_IN)


def test_a_capability_that_RETURNS_something_must_check_it() -> None:
    with pytest.raises(ValueError, match="checkpoints nothing"):
        _capability(checkpoints=())


def test_a_sensitive_slot_cannot_be_EXTRACTED_back_out() -> None:
    """Rule 3 covers the way IN. This is the way OUT, and it was missing.

    `username`/`password`/`ssn` may be written from an `input_ref` and never
    read. Without this an EXTRACT into `password` would lift a secret off the
    screen and hand it to the caller through `returns` -- past a redaction
    rule that only ever guarded inputs.

    ⚠️ Not hypothetical. A real discovery run emitted exactly this shape for
    `username` on 2026-09-28, and the artifact validated. The disk test that
    should have caught it CRASHED on a `None` instead of reporting, which is
    why it went unnoticed -- a check that errors is not a check that fails.
    """
    leaky = _capability(
        returns=(OutputSpec(name="who", slot="username"),),
        steps=(
            Step(
                verb=StepVerb.EXTRACT,
                control=ControlRef(screen="overview", control_id="welcome_banner"),
                slot="username",
                output="who",
                note="lift the logged-in username and hand it back",
            ),
        ),
        checkpoints=(
            Checkpoint(
                output="who",
                expected=LiteralValue(value="john"),
                why="proves we read the logged-in user",
            ),
        ),
    )
    with pytest.raises(CapabilityError, match="never read back out"):
        validate_capability(leaky)


def test_a_committed_TRACE_carries_no_balance_or_secret() -> None:
    """The redaction claim, checked against the files that ship.

    ⚠️ `value_length, never the value` was only ever true of INPUTS. Extracted
    OUTPUTS were written verbatim, so committed traces carried
    `"value": "$1231.10"` and repeated it in `outputs` -- while REPORT.md,
    evidence/README.md and issue #7 all described the gap as "screenshots
    only". Copilot found it by reading the committed evidence, not the code,
    which is why this test reads the evidence too.

    `account_id` is deliberately NOT masked: evidence whose job is proving
    WHICH record was read has to name the record.
    """
    import json
    import subprocess

    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "evidence/runs"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    ).stdout.splitlines()
    traces = [ROOT / f for f in tracked if f.endswith("trace.jsonl")]
    assert traces, "no committed traces; this test would assert nothing"

    money = re.compile(r"\$\s?\d[\d,]*\.\d\d")
    offenders: list[str] = []
    for trace in traces:
        for n, line in enumerate(trace.read_text().splitlines(), 1):
            event = json.loads(line)
            if event.get("event") not in {"extracted", "replay_succeeded"}:
                continue
            blob = json.dumps({k: v for k, v in event.items() if k in {"value", "outputs"}})
            if money.search(blob):
                offenders.append(f"{trace.parent.name}:{n} {blob[:90]}")
    assert not offenders, "regulated values in committed evidence:\n  " + "\n  ".join(offenders)


def test_every_approved_artifact_the_docs_and_tests_LOAD_is_committed() -> None:
    """`.gitignore` excludes approved artifacts, so committing one is deliberate.

    ⚠️ And I forgot to. `request_loan.v2.approved.json` was created, approved,
    referenced by the README and by `test_value_risk_live.py` -- and never
    added, because `git add -A` respects `.gitignore`. A fresh clone got
    `FileNotFoundError` on the documented demo and on the live suite. Found by
    Copilot on PR #5's second pass.

    The ignore rule is right: approval is a person's act and a new approved
    artifact should not slip in unnoticed. What was missing is the check that
    the deliberate act happened.
    """
    import re
    import subprocess

    tracked = set(
        subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "artifacts"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout.split()
    )
    referenced: set[str] = set()
    for path in (ROOT / "README.md", *(ROOT / "tests").glob("*.py")):
        referenced |= set(re.findall(r"artifacts/[a-z_]+\.v\d+\.approved\.json", path.read_text()))
    assert referenced, "nothing references an approved artifact; this asserted nothing"
    missing = sorted(referenced - tracked)
    assert not missing, "referenced but NOT committed (git add -f each): " + ", ".join(missing)


def test_a_capability_is_addressed_by_NAME_not_by_filename() -> None:
    """`--capability read_savings_balance`, not a path into `artifacts/`.

    A filename leaks three things a caller should not know: where artifacts
    live, which version is current, and the approval suffix. An agent invoking
    a capability knows its NAME.
    """
    assert resolve_artifact(ARTIFACTS, "read_savings_balance").name.endswith(".v3.approved.json")
    assert resolve_artifact(ARTIFACTS, "request_loan", version=1).name.endswith(".v1.approved.json")


def test_resolving_a_name_with_only_DRAFTS_refuses_and_says_how() -> None:
    """Replay must not reach a draft by accident, and the error must be useful."""
    with pytest.raises(KeyError, match="approve"):
        resolve_artifact(ARTIFACTS, "evidence_discovery")
    # ...unless the caller explicitly asks for one, which tests and `check` do.
    assert resolve_artifact(ARTIFACTS, "evidence_discovery", approved_only=False).name.endswith(
        ".draft.json"
    )


def test_an_unknown_name_lists_what_IS_there() -> None:
    """A registry that says "not found" and stops is a registry you cannot browse."""
    with pytest.raises(KeyError, match="read_savings_balance"):
        resolve_artifact(ARTIFACTS, "no_such_capability")


def test_version_10_does_not_sort_below_version_9() -> None:
    """Lexical sort on filenames is the classic way to pick the wrong artifact."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for v in (9, 10):
            (root / f"c.v{v}.approved.json").write_text("{}")
        assert resolve_artifact(root, "c").name == "c.v10.approved.json"
