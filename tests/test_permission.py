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


def test_a_star_permits_everything_and_an_unlisted_tenant_is_REFUSED() -> None:
    """⚠️ The `unlisted` line used to assert `is None` -- the third test in this
    repo that pinned a fail-open as if it were the feature.

    `*` is an explicit decision to restrict nothing and stays. Being absent
    from a configured gate is not a decision, it is an omission, and answering
    an omission with "unrestricted" is how a typo outranks the real name.
    """
    settings = Settings(
        interfaceai_allowed_capabilities="baseline=*;feature=log_in,read_savings_balance"
    )
    assert settings.allowed_capabilities("baseline") is None
    assert settings.allowed_capabilities("feature") == frozenset({"log_in", "read_savings_balance"})
    with pytest.raises(ValueError, match="no capability policy"):
        settings.allowed_capabilities("unlisted")


def test_the_gate_is_opt_in() -> None:
    """An ENTIRELY unconfigured gate stays off. Nobody opted in."""
    assert Settings(interfaceai_allowed_capabilities="").allowed_capabilities("anyone") is None


def test_an_UNKNOWN_tenant_is_refused_once_the_gate_IS_configured() -> None:
    """The fail-open Copilot found, and the distinction that makes it one.

    An unconfigured gate returning None is a decision. A CONFIGURED gate that
    does not mention this tenant returning None is a hole: `--tenant freature`
    got no restriction at all while the correctly spelled `feature` got the
    allowlist. A misspelling that grants MORE permission than the real name is
    the worst direction for a guard to fail.
    """
    settings = Settings(interfaceai_allowed_capabilities="feature=log_in")
    assert settings.allowed_capabilities("feature") == frozenset({"log_in"})
    with pytest.raises(ValueError, match="no capability policy"):
        settings.allowed_capabilities("freature")


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


def test_every_capability_the_README_tells_you_to_replay_is_PERMITTED() -> None:
    """The config must not silently break the documentation.

    ⚠️ `feature` permitted `log_in,read_savings_balance` while the README's
    cross-tenant demo replays `log_in_discovered`, so the documented proof of
    §3.7 died at pre-flight with "not permitted for feature". I had SEEN that
    failure and moved past it; Copilot read the config against the docs.

    `request_loan`'s absence from `feature` is the real demonstration and is
    asserted below, so this test cannot be satisfied by permitting everything.
    """
    import re

    readme = (ROOT / "README.md").read_text()
    settings = Settings()
    checked = 0
    for line in readme.splitlines():
        match = re.search(r"interfaceai replay\s+artifacts/([a-z_]+)\.v\d+", line)
        if not match:
            continue
        tenant = "feature" if "--tenant feature" in line else "baseline"
        permitted = settings.allowed_capabilities(tenant)
        checked += 1
        assert permitted is None or match.group(1) in permitted, (
            f"README replays {match.group(1)!r} on {tenant!r}, which does not permit it"
        )
    assert checked, "no replay commands found in the README; this asserted nothing"

    # and the exclusion that carries the demonstration still stands
    assert "request_loan" not in (settings.allowed_capabilities("feature") or set())
