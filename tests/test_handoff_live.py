"""Human handoff: pause, hand over the live session, verify, resume (3.6).

`live` — the point is that the human operates the SAME browser mid-run, which
needs a real one.

The scenario is real, not staged: `env break` removes account 12345, so the
recorded `extract` step cannot find its control and the run blocks. A scripted
operator then drives the live page and hands control back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from interfaceai import parabank
from interfaceai.capability import load_capability
from interfaceai.control_map_store import ControlMapStore
from interfaceai.handoff import (
    HumanResolution,
    InterventionRequest,
    Owner,
    Resolution,
    ScriptedOperator,
)
from interfaceai.outcomes import NeedsOperator
from interfaceai.replay import replay
from interfaceai.settings import get_settings
from interfaceai.vision_llm import call_vision_llm

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "log_in_discovered.v1.approved.json"

pytestmark = pytest.mark.live


def _replay(operator):
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
        operator=operator,
    )


@pytest.fixture
def account_12345_is_gone():
    if not parabank.is_seeded():
        pytest.skip("ParaBank is not up; run `interfaceai env reset`")
    parabank.ParaBankAdmin().clean_db()
    yield
    parabank.ParaBankAdmin().init_db()


@pytest.mark.usefixtures("account_12345_is_gone")
def test_the_operator_is_offered_the_live_session_and_can_abort() -> None:
    """Abort is the honest default when the state cannot be restored.

    The operator looks, cannot make 12345 exist, and says so. The run reports
    NeedsOperator with the human's note — not a silent failure, and not a
    guess.
    """
    seen: list[InterventionRequest] = []

    class Watching(ScriptedOperator):
        def resolve(self, request, surface) -> HumanResolution:
            seen.append(request)
            return super().resolve(request, surface)

    result = _replay(Watching(["url", "abort account 12345 no longer exists"]))

    assert isinstance(result, NeedsOperator), result
    assert len(seen) == 1, "the operator should have been asked exactly once"

    request = seen[0]
    assert "12345_link" in request.why
    assert request.capability == "log_in_discovered"
    assert "click log_in_button" in request.completed_steps
    assert request.location.startswith("http://localhost:8080")
    assert "no longer exists" in result.why


@pytest.mark.usefixtures("account_12345_is_gone")
def test_the_handoff_is_recorded_with_ownership_in_the_evidence() -> None:
    """3.6: 'preserve context and evidence across the handoff, and record what
    the human did.'"""
    import json

    result = _replay(ScriptedOperator(["click 5 5", "abort done looking"]))
    assert result.evidence_dir is not None

    events = [
        json.loads(line) for line in (result.evidence_dir / "trace.jsonl").read_text().splitlines()
    ]
    kinds = [e["event"] for e in events]
    assert "handoff_requested" in kinds
    assert "human_acted" in kinds
    assert "handoff_returned" in kinds

    requested = next(e for e in events if e["event"] == "handoff_requested")
    returned = next(e for e in events if e["event"] == "handoff_returned")
    assert requested["owner"] == Owner.HUMAN
    assert returned["owner"] == Owner.WORKER
    assert returned["resolution"] == Resolution.ABORTED
    assert returned["human_actions"] == 1

    acted = next(e for e in events if e["event"] == "human_acted")
    assert acted["x"] == 5 and acted["y"] == 5


@pytest.mark.usefixtures("account_12345_is_gone")
def test_resume_re_verifies_and_will_not_advance_on_a_missing_control() -> None:
    """The resume rule: an extract whose target is still absent stays paused.

    The operator resumes without fixing anything. Replay re-observes, finds the
    control still missing, and refuses to advance — rather than trusting the
    word 'resume'.
    """
    result = _replay(ScriptedOperator(["resume nothing changed"]))
    assert isinstance(result, NeedsOperator), result
    assert "still not on screen" in result.why
