"""One artifact, two tenants (3.7). `live` — needs both compose profiles up.

    docker compose --profile tenant-b up -d --wait
    uv run interfaceai env reset && uv run interfaceai env reset --tenant-b

The brief asks how an artifact is represented so it can be reused across
institutions running the same vendor product. The answer here is structural:
the artifact names controls, the control maps hold the pixels, and the maps are
keyed by tenant. Nothing about the artifact is tenant-specific except which map
it is resolved against.

⚠️ **Honest limit.** `parabank:baseline` and `parabank:feature` are different
image digests but both ship the stock, unbranded UI — measured 19/19 and 22/22
locators matching at 1.0000. So this proves the reuse PATH works; it does not
prove the design survives a restyled tenant. `adopt_control_map` is what would
catch that case, and its refusal is tested below.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from interfaceai import parabank
from interfaceai.capability import load_capability
from interfaceai.control_map_store import (
    ControlMapStore,
    MapKey,
    adopt_control_map,
)
from interfaceai.outcomes import Success
from interfaceai.replay import replay
from interfaceai.settings import get_settings
from interfaceai.surface import PlaywrightSurface
from interfaceai.vision_llm import call_vision_llm

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts" / "log_in_discovered.v1.approved.json"
MAPS = ControlMapStore(ROOT / "control_maps")

pytestmark = pytest.mark.live


@pytest.fixture
def both_tenants():
    settings = get_settings()
    for url in (settings.parabank_base_url, settings.parabank_b_base_url):
        if not parabank.is_seeded(url):
            pytest.skip(f"{url} is not seeded; start the tenant-b profile and reseed")
    parabank.ParaBankAdmin(settings.parabank_base_url).init_db()
    parabank.ParaBankAdmin(settings.parabank_b_base_url).init_db()


@pytest.mark.usefixtures("both_tenants")
def test_the_same_artifact_replays_on_a_tenant_it_was_never_recorded_on() -> None:
    settings = get_settings()
    recorded = load_capability(ARTIFACT)
    assert recorded.target.tenant == "baseline", "this artifact was recorded on tenant A"

    other = recorded.model_copy(
        update={
            "target": recorded.target.model_copy(
                update={"tenant": "feature", "base_url": settings.parabank_b_base_url}
            )
        }
    )
    result = replay(
        other,
        {},
        store=MAPS,
        evidence_root=ROOT / "evidence" / "runs",
        secrets={
            "parabank_username": settings.parabank_demo_username,
            "parabank_demo_password": settings.parabank_demo_password.get_secret_value(),
        },
        vision=call_vision_llm,
        allowed_origins=settings.allowed_origins,
    )
    assert isinstance(result, Success), result
    assert result.outputs["account_id"] == "12345"


@pytest.mark.usefixtures("both_tenants")
def test_adoption_verifies_every_locator_against_the_target_tenant() -> None:
    """Copying a map blindly would answer 'yes' for reasons nobody checked."""
    settings = get_settings()
    with PlaywrightSurface(allowed_origins=settings.allowed_origins) as surface:
        surface.navigate(f"{settings.parabank_b_base_url}/index.htm")
        surface.wait(1.0)
        report = adopt_control_map(
            MAPS,
            MapKey(app="parabank", tenant="baseline", screen="index"),
            MapKey(app="parabank", tenant="feature", screen="index"),
            surface.screenshot(),
        )
    assert report.clean, f"drifted: {report.drifted}"
    source = MAPS.get(MapKey(app="parabank", tenant="baseline", screen="index"))
    ready = [c for c in source.controls if c.status == "ready"]
    assert len(report.matched) == len(ready), "every grounded control must be verified"
    assert report.matched, "verifying nothing is not a clean bill of health"


@pytest.mark.usefixtures("both_tenants")
def test_adoption_REFUSES_and_writes_nothing_when_the_screen_differs() -> None:
    """A partially-adopted map fails at replay, far from the cause.

    Verified against a genuinely different screen rather than a synthetic one:
    the login page's locators do not match the accounts overview.
    """
    settings = get_settings()
    target = MapKey(app="parabank", tenant="probe_tenant", screen="index")
    with PlaywrightSurface(allowed_origins=settings.allowed_origins) as surface:
        surface.navigate(f"{settings.parabank_b_base_url}/about.htm")
        surface.wait(1.0)
        report = adopt_control_map(
            MAPS,
            MapKey(app="parabank", tenant="baseline", screen="index"),
            target,
            surface.screenshot(),
        )
    assert not report.clean
    assert report.drifted
    assert MAPS.screens("parabank", "probe_tenant") == [], "nothing may be written on drift"
