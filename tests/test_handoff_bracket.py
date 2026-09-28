"""The window in which a human owns the page is bracketed by evidence.

A `human_acted` event is written for every action taken THROUGH the operator
surface. Nothing is written when the human reaches past it and clicks the
visible browser directly, which they physically can -- so the per-action log is
complete for one path and blind to the other.

These tests pin the weaker claim that holds for both: whatever the human did,
the run records what the page looked like when we handed it over and what it
looked like when we got it back.
"""

from __future__ import annotations

import json
from pathlib import Path

from interfaceai.capabilities import SESSION_LOSS_PROBE
from interfaceai.capability import Step, StepVerb
from interfaceai.control_map_store import ControlMapStore
from interfaceai.evidence import EvidenceWriter
from interfaceai.handoff import Owner, ScriptedOperator
from interfaceai.outcomes import NeedsOperator
from interfaceai.replay import _Ctx, _hand_over
from interfaceai.surface import ActionPolicy

# A one-pixel PNG. The bracket is about WHEN a frame was taken, not what is in
# it, so the cheapest valid image is the honest fixture.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6300010000050001"
    "0d0a2db4"
    "0000000049454e44ae426082"
)


class _FakeSurface:
    """Enough surface for a handoff: a URL that moves and a frame to take."""

    def __init__(self, url: str) -> None:
        self._url = url
        self.shots = 0

    def current_url(self) -> str:
        return self._url

    def screenshot(self) -> bytes:
        self.shots += 1
        return _PNG

    def navigate(self, url: str) -> None:
        self._url = url


def _ctx(tmp_path: Path, surface: _FakeSurface, commands: list[str]) -> _Ctx:
    return _Ctx(
        capability=SESSION_LOSS_PROBE,
        inputs={},
        secrets={},
        store=ControlMapStore(tmp_path / "maps"),
        surface=surface,  # type: ignore[arg-type]
        evidence=EvidenceWriter(tmp_path, goal="handoff bracket"),
        off=None,
        vision=None,
        policy=ActionPolicy(),
        confirm_risky=False,
        outputs={},
        done=[],
        operator=ScriptedOperator(commands),
    )


def _events(ctx: _Ctx) -> list[dict]:
    return [
        json.loads(line) for line in (ctx.evidence.dir / "trace.jsonl").read_text().splitlines()
    ]


def _one(ctx: _Ctx, kind: str) -> dict:
    found = [e for e in _events(ctx) if e["event"] == kind]
    assert len(found) == 1, f"expected exactly one {kind}, got {len(found)}"
    return found[0]


_BLOCKED = NeedsOperator(
    why="the page asked for something the artifact does not describe",
    step_index=0,
    screen="overview",
    evidence_dir=Path("unused"),
    completed_steps=(),
)
_OBSERVE = Step(verb=StepVerb.OBSERVE, note="a step with no control, so resume advances")


def test_both_edges_of_the_handoff_carry_a_frame(tmp_path: Path) -> None:
    surface = _FakeSurface("http://bank/overview.htm")
    ctx = _ctx(tmp_path, surface, ["resume"])

    assert _hand_over(ctx, 0, _OBSERVE, _BLOCKED) == "advance"

    before = _one(ctx, "handoff_requested")
    after = _one(ctx, "handoff_returned")
    for edge in (before, after):
        assert Path(edge["frame"]).exists(), f"{edge['event']} frame was not written"
        assert edge["url"] == "http://bank/overview.htm"
    assert before["frame"] != after["frame"], "one frame reused for both edges proves nothing"


def test_a_human_who_navigates_is_visible_even_though_we_never_saw_the_click(
    tmp_path: Path,
) -> None:
    """The whole point: the ACTION may be invisible, the EFFECT is not."""
    surface = _FakeSurface("http://bank/overview.htm")
    ctx = _ctx(tmp_path, surface, ["goto http://bank/activity.htm", "resume"])

    _hand_over(ctx, 0, _OBSERVE, _BLOCKED)

    after = _one(ctx, "handoff_returned")
    assert after["url_changed"] is True
    assert after["url"] == "http://bank/activity.htm"
    assert _one(ctx, "handoff_requested")["url"] == "http://bank/overview.htm"


def test_a_human_who_changes_nothing_says_so(tmp_path: Path) -> None:
    """`url_changed` false is a reading, not a missing value."""
    ctx = _ctx(tmp_path, _FakeSurface("http://bank/overview.htm"), ["resume"])

    _hand_over(ctx, 0, _OBSERVE, _BLOCKED)

    assert _one(ctx, "handoff_returned")["url_changed"] is False


def test_the_bracket_is_recorded_even_when_the_operator_aborts(tmp_path: Path) -> None:
    """An abandoned run is exactly the one whose evidence gets read."""
    surface = _FakeSurface("http://bank/overview.htm")
    ctx = _ctx(tmp_path, surface, ["goto http://bank/error.htm", "abort not my call"])

    result = _hand_over(ctx, 0, _OBSERVE, _BLOCKED)

    assert isinstance(result, NeedsOperator)
    after = _one(ctx, "handoff_returned")
    assert after["resolution"] == "aborted"
    assert Path(after["frame"]).exists()
    assert after["url_changed"] is True


def test_ownership_is_recorded_on_both_edges(tmp_path: Path) -> None:
    """3.6: "there must be a way to know who is (or should be) in control"."""
    ctx = _ctx(tmp_path, _FakeSurface("http://bank/overview.htm"), ["resume"])

    _hand_over(ctx, 0, _OBSERVE, _BLOCKED)

    assert _one(ctx, "handoff_requested")["owner"] == str(Owner.HUMAN)
    assert _one(ctx, "handoff_returned")["owner"] == str(Owner.WORKER)
    assert ctx.owner is Owner.WORKER
