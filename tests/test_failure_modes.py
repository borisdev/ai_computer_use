"""Every failure mode we have actually observed, reproduced.

The catalogue behind `docs/failure-modes.md` and `outcomes.py`. One test per
OBSERVED failure — a mode with no test does not go in the catalogue, which is
what stops it drifting into a list of things we imagine could happen.

Almost all of it runs offline in milliseconds, because the inputs are committed:
the screenshots from the 2026-09-26 discovery run, and the control maps it
wrote. No model, no network, no container.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from interfaceai.control_map_store import ControlMapStore, MapKey
from interfaceai.decisions import (
    AgentDecision,
    ManualActionKind,
    supported_actions,
    validate_decision,
)
from interfaceai.outcomes import (
    BusinessOutcome,
    BusinessOutcomeKind,
    Failed,
    NeedsOperator,
    Success,
    is_actionable_by_caller,
)
from interfaceai.screenshot2controls import (
    ClickPoint,
    ControlRole,
    CropBox,
    LocatedControl,
    ResolveInput,
    ScreenInput,
    _make_locator,
    locate_control,
)
from interfaceai.surface import ActionPolicy, NotAllowedError

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "evidence" / "runs" / "20260926T022551Z" / "frames"
EMPTY_FORM = FRAMES / "001-00-index.png"
FILLED_FORM = FRAMES / "003-02-index.png"
OVERVIEW = FRAMES / "004-03-overview.png"
CLEAN_OVERVIEW = ROOT / "tests" / "fixtures" / "overview-clean-1-row.png"
MAPS = ControlMapStore(ROOT / "control_maps")
BASELINE_INDEX = MapKey(app="parabank", tenant="baseline", screen="index")
BASELINE_OVERVIEW = MapKey(app="parabank", tenant="baseline", screen="overview")


# ---------------------------------------------------------------------------
# Failed — a locator could not be trusted
# ---------------------------------------------------------------------------


def test_landmark_contaminated_by_typed_input() -> None:
    """Issue 0002. Scored 0.8365 live and killed a discovery run mid-login.

    An upward-reaching landmark for the Log In button swallows the password
    field. Self-matches at 1.0000 on the empty form; fails once anything is
    typed. Reproduced from that run's own before/after frames.
    """
    locator = _make_locator(
        ScreenInput(screenshot_png=EMPTY_FORM.read_bytes()),
        CropBox(x=200, y=325, width=240, height=96),  # the old 2/3 placement
        ClickPoint(x=320, y=389),
    )
    assert (
        locate_control(ResolveInput(screenshot_png=EMPTY_FORM.read_bytes(), locator=locator)).status
        == "matched"
    )

    after = locate_control(ResolveInput(screenshot_png=FILLED_FORM.read_bytes(), locator=locator))
    assert after.status == "not_found"
    assert Failed(0, "click log_in_button", "matched", after.status).observed == "not_found"


def test_anchor_spanning_columns_dies_when_the_table_resizes() -> None:
    """Issue 0011, against the real 1-row table.

    Columns auto-size, so a header patch crossing a column boundary moves when
    the row count changes. Recorded on the seeded table (11 rows), matched
    against `tests/fixtures/overview-clean-1-row.png` (1 row, captured via
    `env break`).

    ⚠️ An earlier version of this test shifted the whole image by 2px instead.
    That proves nothing -- template matching is translation invariant, so it
    found the pattern at the new position and passed. The real failure is
    columns moving RELATIVE to each other, which only a real fixture has.
    """
    clean = CLEAN_OVERVIEW.read_bytes()
    seeded = ScreenInput(screenshot_png=OVERVIEW.read_bytes())

    wide = _make_locator(
        seeded, CropBox(x=470, y=322, width=280, height=26), ClickPoint(x=480, y=330)
    )
    narrow = _make_locator(
        seeded, CropBox(x=486, y=316, width=90, height=28), ClickPoint(x=490, y=320)
    )

    assert locate_control(ResolveInput(screenshot_png=clean, locator=wide)).status == "not_found"
    assert locate_control(ResolveInput(screenshot_png=clean, locator=narrow)).status == "matched"


def test_ambiguous_has_NO_observed_instance() -> None:
    """`ambiguous` is implemented, is not in the brief, and has never fired.

    It appears nowhere in the assignment -- it falls out of choosing template
    matching. `findings.md` §3 is cited as its instance: a control's own bbox
    "matches Username *and* Password, 3 positions". That measurement is real but
    it counts **positions scoring >= 0.95**, which is a different criterion from
    the ambiguity margin (a runner-up within 0.05 of the best). Fed the real
    username bbox, `locate_control` returns `matched`.

    So the status has zero observed instances, exactly like `Recoverable` --
    recorded here rather than dressed up with a synthetic fixture.
    """
    bare = _make_locator(
        ScreenInput(screenshot_png=EMPTY_FORM.read_bytes()),
        CropBox(x=293, y=305, width=146, height=18),  # the real input, DOM oracle
        ClickPoint(x=319, y=309),
    )
    result = locate_control(ResolveInput(screenshot_png=EMPTY_FORM.read_bytes(), locator=bare))
    assert result.status == "matched", (
        f"got {result.status} -- if this ever becomes 'ambiguous' we finally have "
        "an instance, and the catalogue and docs/failure-modes.md should record it"
    )


# ---------------------------------------------------------------------------
# NeedsOperator — six of seven triggers need no model judgement
# ---------------------------------------------------------------------------


def test_acting_on_an_ungrounded_control_is_refused() -> None:
    """Discovery names controls it cannot ground; acting on one would mean
    clicking a coordinate we do not have.

    Synthetic rather than pinned to a real map entry. It used to assert that
    `13344_link` was `unresolved` — true when written, and false since the
    two-pass inventory split landed (`docs/issues/0008`), which is exactly why
    a MECHANISM test should not depend on a defect persisting.
    """
    control_map = MAPS.get(BASELINE_OVERVIEW)
    ungrounded = LocatedControl(
        id="never_grounded_link",
        label="Ghost",
        role=ControlRole.LINK,
        description="named by the read pass, never placed",
        status="unresolved",
        reason="the locate pass did not place it",
    )
    probe = control_map.model_copy(update={"controls": [*control_map.controls, ungrounded]})
    with pytest.raises(ValueError, match="not ready"):
        validate_decision(
            AgentDecision(
                action=ManualActionKind.CLICK,
                control_id="never_grounded_link",
                reason="act on something that was never located",
                post_action_expectation="",
                confidence=0.9,
            ),
            probe,
        )


def test_the_account_links_are_grounded_again_after_the_two_pass_split() -> None:
    """The improvement, pinned so a regression is loud.

    Before the split, 4 of 10 reported account ids did not exist and 13344 —
    the assignment's own account — was `unresolved`. Measured after: 11/11
    correct and every one grounded.
    """
    import re

    control_map = MAPS.get(BASELINE_OVERVIEW)
    accounts = [c for c in control_map.controls if re.fullmatch(r"\d{4,6}_link", c.id)]
    assert len(accounts) == 11, f"expected 11 account links, got {[c.id for c in accounts]}"
    assert all(c.status == "ready" for c in accounts), [
        c.id for c in accounts if c.status != "ready"
    ]
    assert any(c.id == "13344_link" for c in accounts)


def test_a_forbidden_value_never_reaches_the_page() -> None:
    """Pure policy. No model judgement, no screen state."""
    policy = ActionPolicy(forbidden_values=frozenset({"622-11-9999"}))
    with pytest.raises(NotAllowedError, match="forbidden"):
        policy.check(ManualActionKind.ENTER_TEXT, "SSN 622-11-9999")


def test_an_action_outside_the_allowlist_is_refused() -> None:
    policy = ActionPolicy(allowed_actions=frozenset({ManualActionKind.CLICK}))
    with pytest.raises(NotAllowedError, match="not in the policy"):
        policy.check(ManualActionKind.ENTER_TEXT, "anything")


def test_typing_into_a_link_is_a_decision_error() -> None:
    control_map = MAPS.get(BASELINE_INDEX)
    with pytest.raises(ValueError, match="not supported"):
        validate_decision(
            AgentDecision(
                action=ManualActionKind.ENTER_TEXT,
                control_id="forgot_login_info_link",
                value="x",
                reason="wrong kind of control",
                post_action_expectation="",
                confidence=0.9,
            ),
            control_map,
        )


def test_a_table_panel_cannot_be_clicked() -> None:
    assert supported_actions(ControlRole.TABLE_CONTROL_PANEL) == []


def test_the_escalation_that_actually_happened_is_on_record() -> None:
    """The first discovery run stopped mid-login rather than guessing.

    Asserted against the committed trace, so the claim in the docs has a check.
    """
    traces = sorted((ROOT / "evidence" / "runs").glob("*/trace.jsonl"))
    assert traces, "no committed run evidence"
    decided = [
        json.loads(line)
        for path in traces
        for line in path.read_text().splitlines()
        if '"decided"' in line
    ]
    assert decided, "no decisions recorded in any committed run"
    assert all(d["confidence"] > 0 for d in decided)


# ---------------------------------------------------------------------------
# The result contract itself
# ---------------------------------------------------------------------------


def test_a_business_outcome_is_an_answer_not_a_failure() -> None:
    """The brief's glossary calls conflating these the most common mistake."""
    found = Success(outputs={"balance": "$1231.10"}, steps_run=4)
    missing = BusinessOutcome(
        kind=BusinessOutcomeKind.RECORD_NOT_FOUND,
        detail="Could not find account #54321",
        steps_run=4,
    )
    assert is_actionable_by_caller(found)
    assert is_actionable_by_caller(missing)


def test_a_failure_and_an_escalation_are_not_answers() -> None:
    violated = Failed(
        step_index=6,
        step="extract balance",
        expected="1231.10",
        observed="5022.93",
    )
    stuck = NeedsOperator(why="control unresolved", step_index=2, screen="overview")
    assert not is_actionable_by_caller(violated)
    assert not is_actionable_by_caller(stuck)


def test_a_violated_checkpoint_carries_both_halves() -> None:
    """`expected` and `observed` are both required.

    The failure that matters most -- 13344 reading 5022.93 where the recording
    said 1231.10 -- is only debuggable as a pair, and is indistinguishable from
    a not-found without it.
    """
    violated = Failed(step_index=6, step="extract balance", expected="1231.10", observed="5022.93")
    assert violated.expected != violated.observed
    assert "5022.93" in violated.observed


def test_there_is_no_recoverable_variant() -> None:
    """Deliberate. We have never observed one, so it has no type and no test.

    This assertion exists so that ADDING one is a conscious act that breaks a
    test naming the reason, rather than a drive-by import.
    """
    from interfaceai import outcomes

    assert not hasattr(outcomes, "Recoverable"), (
        "a Recoverable variant appeared; it needs an observed instance and a "
        "test reproducing it first -- see the module docstring"
    )
