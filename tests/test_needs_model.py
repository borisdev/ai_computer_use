"""A keyless reviewer must be refused before the browser starts.

⛔ THE FAILURE THESE GUARD AGAINST, stated so the checks can go red on it:
someone reads `needs_model` and "simplifies" it to a verb scan, because that
is the obvious shape. `request_loan` then reports False, a reviewer with no
key gets forty lines of asyncio traceback on their first command, and the
real message sits at the bottom of it.

That is not hypothetical -- it is what the README claimed, twice, and what a
cold clone actually did on 2026-09-30.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from interfaceai import vision_llm
from interfaceai.capability import Capability, StepVerb, needs_model

ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"


def _library() -> dict[str, Capability]:
    lib: dict[str, Capability] = {}
    for path in ARTIFACTS.glob("*.approved.json"):
        cap = Capability.model_validate(json.loads(path.read_text()))
        lib[cap.name] = cap
    return lib


def test_a_panel_read_needs_the_model_even_with_no_extract_verb() -> None:
    """The exact artifact that made the verb heuristic look right.

    `request_loan` has no `extract` step anywhere. It still calls the model,
    because one step reads a TABLE_CONTROL_PANEL -- and a panel read is not
    spelled as a verb. Checking `verbs` is how this was missed twice.
    """
    lib = _library()
    loan = lib["request_loan"]

    verbs = {s.verb for s in loan.steps}
    assert StepVerb.EXTRACT not in verbs, (
        "premise of this test: request_loan has no extract step. If that "
        "changed, the test no longer exercises the panel route -- pick "
        "another artifact rather than deleting the assertion."
    )
    assert needs_model(loan, lib) is True


def test_log_in_is_the_one_that_replays_with_no_key() -> None:
    """The README's keyless promise, as a check rather than a sentence.

    It named `log_in_discovered` for two weeks. That one HAS an extract step.
    """
    lib = _library()
    assert needs_model(lib["log_in"], lib) is False
    assert needs_model(lib["log_in_discovered"], lib) is True


def test_a_capability_needs_the_model_when_what_it_invokes_does() -> None:
    """One layer down still counts, which a flat scan of `steps` would miss."""
    lib = _library()
    reader = lib["read_savings_balance"]
    assert any(s.verb is StepVerb.INVOKE for s in reader.steps)
    assert needs_model(reader, lib) is True


def test_missing_key_answers_without_calling_anything(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pre-flight probe that made a network call would defeat its own point."""
    monkeypatch.setattr(vision_llm.litellm, "acompletion", None)
    verdict = vision_llm.missing_key("openai-gpt-4.1")
    assert verdict is None or "OPENAI_API_KEY" in verdict


def test_an_unknown_profile_is_reported_not_swallowed() -> None:
    """A typo in VISION_PROFILE must be loud. Silence here reads as 'configured'."""
    verdict = vision_llm.missing_key("gpt-4.1-typo")
    assert verdict is not None
    assert "not a known profile" in verdict
