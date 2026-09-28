"""Which capabilities a tenant permits — and that composition cannot dodge it.

⚠️ **This gate is make-believe, and saying so is the point.** ParaBank has no
roles and no authorization model, so this is OUR policy modelling what a real
deployment would enforce. It is a §3.4 *guardrail*, not a §3.3 *permission
denial* — the latter is the application telling an operator no, and we still
have no instance of it (`docs/failure-modes.md`).

The fiction is worth having because the SHAPE is real: a bank does restrict
which operations an integration may perform, per institution, and such a check
has to survive composition.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from interfaceai.capabilities import LIBRARY
from interfaceai.capability import approve, load_capability
from interfaceai.control_map_store import ControlMapStore
from interfaceai.outcomes import Failed
from interfaceai.replay import replay
from interfaceai.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
MAPS = ControlMapStore(ROOT / "control_maps")


def _loan():
    return load_capability(ROOT / "artifacts" / "request_loan.v1.approved.json")


def _replay(capability, permitted):
    """No vision, no browser — the gate must refuse before either is touched."""
    return replay(
        capability,
        {"amount": "1", "down_payment": "1"},
        store=MAPS,
        evidence_root=ROOT / "evidence" / "runs",
        permitted=permitted,
        library={n: approve(c, "test") for n, c in LIBRARY.items()},
    )


# --- configuration ---------------------------------------------------------


def test_a_star_permits_everything_and_an_unlisted_tenant_is_unrestricted() -> None:
    settings = Settings(
        interfaceai_allowed_capabilities="baseline=*;feature=log_in,read_savings_balance"
    )
    assert settings.allowed_capabilities("baseline") is None
    assert settings.allowed_capabilities("unlisted") is None
    assert settings.allowed_capabilities("feature") == frozenset({"log_in", "read_savings_balance"})


def test_the_gate_is_opt_in() -> None:
    """A tenant nobody configured is not accidentally locked out."""
    assert Settings(interfaceai_allowed_capabilities="").allowed_capabilities("anyone") is None


# --- the gate --------------------------------------------------------------


def test_a_forbidden_capability_is_refused_before_a_browser_opens() -> None:
    result = _replay(_loan(), frozenset({"log_in", "read_savings_balance"}))
    assert isinstance(result, Failed), result
    assert result.step == "pre-flight"
    assert "request_loan" in result.expected
    assert "read_savings_balance" in result.observed


def test_a_permitted_capability_passes_the_gate() -> None:
    """It gets past PERMISSION and stops at the next real check, not this one."""
    result = _replay(_loan(), frozenset({"request_loan", "log_in"}))
    assert not (isinstance(result, Failed) and "permitted" in str(result.expected))


def test_no_allowlist_means_no_gate() -> None:
    result = _replay(_loan(), None)
    assert not (isinstance(result, Failed) and "permitted" in str(result.expected))


# --- and composition cannot dodge it ---------------------------------------


def test_a_permitted_capability_cannot_INVOKE_a_forbidden_one() -> None:
    """The reason this is checked at every invoke, not only at the entry.

    `request_loan` invokes `log_in`. Permitting the parent while forbidding the
    child must not let the child run -- otherwise the gate is a front door with
    the back door open.
    """
    result = _replay(_loan(), frozenset({"request_loan"}))
    assert isinstance(result, Failed), result
    assert result.step == "invoke log_in"
    assert "log_in" in result.expected


def test_the_refusal_is_ours_and_is_NOT_a_business_outcome() -> None:
    """A business outcome is the BANK's answer -- "no such member".

    Conflating our guardrail with the application's verdict is the mistake this
    result contract exists to prevent, and the brief's glossary names it.
    """
    from interfaceai.outcomes import BusinessOutcome, is_actionable_by_caller

    result = _replay(_loan(), frozenset({"log_in"}))
    assert not isinstance(result, BusinessOutcome)
    assert not is_actionable_by_caller(result)


@pytest.mark.parametrize("permitted", [frozenset(), frozenset({"something_else"})])
def test_an_empty_or_unrelated_allowlist_refuses(permitted: frozenset[str]) -> None:
    result = _replay(_loan(), permitted)
    assert isinstance(result, Failed)
    assert result.step == "pre-flight"
