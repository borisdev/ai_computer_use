"""A lost session, re-established, once — the brief's *recoverable condition*.

`live` — needs ParaBank up and seeded.

⚠️ **The fault is injected**, the way `env break` injects a changed record.
ParaBank's real session timeout is far too long to wait for, so
`session_loss_probe` throws the session away mid-capability by clicking Log Out
and then carries on as if nothing happened.

That is a faithful stand-in: logged-out `overview.htm` serves **HTTP 200 with
the same heading and an empty table**, so nothing about the response says the
session is gone. A status code would not catch it and neither would a checkpoint.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from interfaceai import parabank
from interfaceai.capabilities import LIBRARY
from interfaceai.capability import approve, load_capability
from interfaceai.control_map_store import ControlMapStore
from interfaceai.outcomes import Failed, NeedsOperator, Success
from interfaceai.replay import replay
from interfaceai.settings import get_settings
from interfaceai.vision_llm import call_vision_llm

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "artifacts" / "session_loss_probe.v1.approved.json"

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def seeded():
    if not parabank.is_seeded():
        pytest.skip("ParaBank is not up; run `interfaceai env reset`")
    parabank.ParaBankAdmin().init_db()


def _run(*, library=None, permitted=None):
    settings = get_settings()
    return replay(
        load_capability(PROBE),
        {"account_id": str(parabank.DEMO_SAVINGS_ACCOUNT_ID)},
        store=ControlMapStore(ROOT / "control_maps"),
        evidence_root=ROOT / "evidence" / "runs",
        secrets={
            "parabank_username": settings.parabank_demo_username,
            "parabank_demo_password": settings.parabank_demo_password.get_secret_value(),
        },
        vision=call_vision_llm,
        allowed_origins=settings.allowed_origins,
        permitted=permitted,
        library=library
        if library is not None
        else {n: approve(c, "test") for n, c in LIBRARY.items()},
    )


def test_a_lost_session_is_re_established_and_the_run_completes() -> None:
    result = _run()
    assert isinstance(result, Success), result
    assert result.outputs["found_account_id"] == "13344"
    assert result.recovered, "a recovered run must not look like a clean one"
    assert "log_in" in result.recovered[0]


def test_the_recovery_is_recorded_in_the_evidence() -> None:
    import json

    result = _run()
    assert result.evidence_dir is not None
    kinds = [
        json.loads(line)["event"]
        for line in (result.evidence_dir / "trace.jsonl").read_text().splitlines()
    ]
    assert "recovering" in kinds
    assert "recovered" in kinds


def test_a_forbidden_capability_stops_the_run_before_recovery_is_reachable() -> None:
    """Permission is checked at every invoke — including the FIRST one.

    ⚠️ This is not the test it was first written as. It claimed to prove that
    recovery cannot re-invoke a forbidden capability. It cannot prove that,
    because with a STATIC allowlist the run dies at step 0: if `log_in` is
    forbidden, it is forbidden the first time too, and recovery is never
    reached.

    The guard in `_try_recover` is therefore **defensive code with no reachable
    path today**. It is kept because every other invoke applies the same check
    and recovery skipping it would be the one hole — and because a deployment
    with per-operator or time-boxed permissions would reach it. Recorded rather
    than pretended to be tested.
    """
    result = _run(permitted=frozenset({"session_loss_probe"}))
    assert isinstance(result, Failed), result
    assert result.step == "invoke log_in"
    assert "log_in to be permitted" in result.expected


def test_without_an_establishes_declaration_there_is_nothing_to_recover() -> None:
    """Recovery is driven by a DECLARED postcondition, not by guessing.

    Strip `establishes` from `log_in` and the same failure is unrecoverable —
    which is the honest behaviour: nothing in the artifact says what that
    capability leaves behind.
    """
    library = {n: approve(c, "test") for n, c in LIBRARY.items()}
    library["log_in"] = library["log_in"].model_copy(update={"establishes": None})
    result = _run(library=library)
    assert isinstance(result, NeedsOperator), result
    assert "not_found" in result.why or "anchor" in result.why
