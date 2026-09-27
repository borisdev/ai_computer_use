"""Deterministic replay, end to end. `live` — needs ParaBank up and seeded.

The thread the assignment asks for, minus discovery (already evidenced):

    approved artifact + inputs -> replay with no model deciding -> typed outcome

Both branches are exercised against the SAME artifact, switched only by the
application's own admin page:

    env reset   Success        outputs a value read off the live screen
    env break   NeedsOperator  the control it needs is gone; stops with context
"""

from __future__ import annotations

from pathlib import Path

import pytest

from interfaceai import parabank
from interfaceai.capability import load_capability
from interfaceai.control_map_store import ControlMapStore
from interfaceai.outcomes import NeedsOperator, Success, is_actionable_by_caller
from interfaceai.replay import replay
from interfaceai.settings import get_settings
from interfaceai.vision_llm import call_vision_llm

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "log_in_discovered.v1.approved.json"

pytestmark = pytest.mark.live


def _replay():
    settings = get_settings()
    return replay(
        load_capability(ARTIFACT),
        {},
        store=ControlMapStore(ROOT / "control_maps"),
        evidence_root=ROOT / "evidence" / "runs",
        secrets={
            "parabank_username": settings.parabank_demo_username,
            "parabank_demo_password": settings.parabank_demo_password.get_secret_value(),
        },
        vision=call_vision_llm,
        allowed_origins=settings.allowed_origins,
    )


@pytest.fixture
def seeded():
    if not parabank.is_seeded():
        pytest.skip("ParaBank is not up; run `interfaceai env reset`")
    parabank.ParaBankAdmin().init_db()
    yield
    parabank.ParaBankAdmin().init_db()


@pytest.fixture
def cleaned():
    if not parabank.is_seeded():
        pytest.skip("ParaBank is not up; run `interfaceai env reset`")
    parabank.ParaBankAdmin().clean_db()
    yield
    parabank.ParaBankAdmin().init_db()


@pytest.mark.usefixtures("seeded")
def test_replay_succeeds_and_returns_a_value_read_from_the_live_screen() -> None:
    result = _replay()
    assert isinstance(result, Success), result
    assert result.outputs["account_id"] == "12345"
    assert result.steps_run == 5
    assert is_actionable_by_caller(result)
    assert (result.evidence_dir / "trace.jsonl").exists()


@pytest.mark.usefixtures("cleaned")
def test_replay_stops_for_a_human_when_the_control_is_gone() -> None:
    """After CLEAN only account 13344 remains, so `12345_link` is not on screen.

    The point is the SHAPE of the stop: it refuses rather than clicking
    something that scored 0.86, and it carries what was already done so a human
    can resume instead of restarting.
    """
    result = _replay()
    assert isinstance(result, NeedsOperator), result
    assert "12345_link" in result.why
    assert not is_actionable_by_caller(result)
    assert "click log_in_button" in result.completed_steps


@pytest.mark.usefixtures("seeded")
def test_a_draft_artifact_is_refused_before_the_browser_opens() -> None:
    """The approval gate, on the production path."""
    from interfaceai.capability import UnapprovedError

    draft = ROOT / "artifacts" / "log_in_discovered.v1.draft.json"
    with pytest.raises(UnapprovedError):
        replay(
            load_capability(draft),
            {},
            store=ControlMapStore(ROOT / "control_maps"),
            evidence_root=ROOT / "evidence" / "runs",
        )
