"""A tenant is a config plus a control map. This is the config half."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from interfaceai.tenant_config import TenantConfig, load_tenant_config

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ROOT / "tenant_configs"


def test_the_shipped_configs_load_and_say_what_they_mean() -> None:
    a = load_tenant_config(CONFIGS / "bank_a.yaml")
    b = load_tenant_config(CONFIGS / "bank_b.yaml")

    assert a.permitted is None, "`*` is an explicit decision to restrict nothing"
    assert b.permitted == frozenset({"log_in", "log_in_discovered", "read_savings_balance"})
    assert "request_loan" not in (b.permitted or set()), (
        "tenant B excluding request_loan IS the demonstration -- see CAPABILITIES.md"
    )
    assert a.confirm_money_above == Decimal(1000)


def test_an_EMPTY_permits_list_means_nothing_not_everything() -> None:
    """The direction a permissions field must fail in.

    An empty allowlist that grants access is how a typo becomes an outage in
    the permissive direction. Same shape as the unlisted-tenant fail-open
    Copilot found in `Settings.allowed_capabilities`.
    """
    cfg = TenantConfig(tenant="t", app="a", base_url="u", permits=())
    assert cfg.permitted == frozenset()
    assert cfg.permitted is not None


def test_a_threshold_that_cannot_gate_anything_is_refused() -> None:
    """`Decimal` accepts NaN and negatives; neither can gate a payment."""
    for bad in ("NaN", "-1", "Infinity"):
        with pytest.raises(ValueError, match="cannot gate|not a number|finite"):
            TenantConfig(tenant="t", app="a", base_url="u", confirm_money_above=Decimal(bad))


def test_an_unparseable_threshold_stops_the_run(tmp_path: Path) -> None:
    """A malformed config is an ERROR, never a default.

    Same rule as the env-var path, learned the same way: `baseline=lots`
    silently disabled a money guardrail while the file still looked like it
    had one.
    """
    bad = tmp_path / "bad.yaml"
    bad.write_text("tenant: t\napp: a\nbase_url: u\nconfirm_money_above: lots\n")
    with pytest.raises(ValueError, match="not a number"):
        load_tenant_config(bad)


def test_a_file_that_is_not_a_mapping_says_so(tmp_path: Path) -> None:
    bad = tmp_path / "list.yaml"
    bad.write_text("- one\n- two\n")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_tenant_config(bad)
