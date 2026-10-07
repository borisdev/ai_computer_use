"""Configuration, loaded from .env (config) and .secret (credentials).

Split follows the nobsmed-v2 convention: .env is committed and holds URLs and
flags, .secret is gitignored and holds anything that would be a finding in a
bank's security review.
"""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".secret"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Target surfaces ---
    parabank_base_url: str = "http://localhost:8080/parabank"
    parabank_b_base_url: str = "http://localhost:8081/parabank"

    # --- Guardrails (assignment 3.4) ---
    # The agent may not touch anything outside these origins. Enforced at the
    # action layer, not by convention.
    interfaceai_allowed_origins: str = "http://localhost:8080,http://localhost:8081"

    # --- Vision model (control mapping) ---
    # Named profiles, mirroring nobsmed-v2's LM_CONFIGS. Which one to use is
    # config; the keys are secrets. Endpoints differ per Azure resource, so
    # each profile names the key it needs.
    vision_profile: str = "gpt-4.1"
    vision_api_key: SecretStr | None = None  # openai-rg-nobsmed  (their API_KEY)
    vision_api_key_eastus2: SecretStr | None = None  # eastus2            (their EASTUS2_API_KEY)
    vision_api_key_west: SecretStr | None = None  # west-us            (their WEST_API_KEY)
    anthropic_api_key_for_vision: SecretStr | None = None
    # ⭐ THE BRING-YOUR-OWN-KEY FIELDS. Every other key above names one of MY
    # Azure resources, so a reviewer cloning this repo cannot use any of them
    # -- measured from a cold clone 2026-09-30: 9 of the 11 README commands
    # died on a missing key they had no way to supply. These two need no
    # endpoint, so `VISION_PROFILE=openai-gpt-4.1` or `VISION_PROFILE=claude-opus`
    # plus the matching key is the whole setup for a stranger.
    openai_api_key: SecretStr | None = None
    # ⭐ POINT THE AZURE PROFILES AT YOUR OWN RESOURCE. Without this the
    # endpoint is baked into `PROFILES` and a reviewer who HAS Azure OpenAI
    # still has to edit source to use it -- the tested path, locked to my
    # subscription by a string. Overriding the URL leaves the code path
    # identical: same provider, same `azure/gpt-4.1`, same litellm call.
    vision_api_base: str | None = None

    # --- Model access ---
    # Read from .secret, which is NOT the process environment -- so it has to be
    # handed to the SDK explicitly. A key sitting in .secret while the SDK reads
    # os.environ is a silent AuthenticationError at the worst moment.
    anthropic_api_key: SecretStr | None = None

    # --- Value-dependent risk (assignment 3.4, per tenant for 3.7) ---
    #
    # One institution's routine transfer is another's exception, so the
    # threshold is tenant config rather than a constant. Read as
    # "tenant=amount", comma separated; a tenant not listed has no threshold
    # and falls back to control-level risk only.
    interfaceai_confirm_money_above: str = "baseline=1000,feature=250"

    # --- Which capabilities a tenant permits (assignment 3.4 + 3.7) ---
    #
    # ⚠️ **MAKE-BELIEVE, and labelled as such.** ParaBank has no roles and no
    # authorization model, so this is OUR gate modelling what a real deployment
    # would enforce -- not the application denying an operator. Those are
    # different things and `docs/failure-modes.md` keeps them apart: a §3.4
    # guardrail refusing is us; a §3.3 permission denial is the bank, and we
    # still have no instance of the latter.
    #
    # It is a fiction worth having because the SHAPE is real: a bank does
    # restrict which operations an integration may perform, per institution,
    # and the check has to survive composition -- a permitted capability must
    # not be able to invoke a forbidden one.
    #
    # "tenant=cap,cap" per tenant, comma separated. `*` permits everything. A
    # tenant not listed permits everything, so the gate is opt-in.
    # Kept in step with `.env` deliberately: the demo must work from a clone
    # that never loads it. `request_loan` is absent from `feature` on purpose --
    # that exclusion IS the demonstration.
    #
    # ⚠️ A tenant NOT named here is REFUSED, not unrestricted. Only an entirely
    # empty setting disables the gate. Adding a tenant to the system means
    # adding it here, or its runs will not start.
    interfaceai_allowed_capabilities: str = (
        "baseline=*;feature=log_in,log_in_discovered,read_savings_balance,discovered_balance"
    )

    # --- Demo fixtures ---
    parabank_demo_username: str = "john"
    parabank_demo_password: SecretStr = Field(default=SecretStr("demo"))

    def key_named(self, field: str) -> str | None:
        """Resolve one of the credential fields above, or its env fallback."""
        secret: SecretStr | None = getattr(self, field, None)
        if secret is not None and secret.get_secret_value():
            return secret.get_secret_value()
        return os.environ.get(field.upper()) or None

    @property
    def anthropic_key(self) -> str | None:
        """The key, from .secret or the environment. None if neither has one."""
        if self.anthropic_api_key is not None:
            return self.anthropic_api_key.get_secret_value() or None
        return os.environ.get("ANTHROPIC_API_KEY") or None

    def allowed_capabilities(self, tenant: str) -> frozenset[str] | None:
        """What this tenant permits. None means no restriction.

        ⛔ AN UNKNOWN TENANT IS REFUSED, NOT WAVED THROUGH. This used to fall
        off the end and `return None`, so `--tenant freature` -- a typo -- got
        NO capability restriction at all, while the correctly spelled `feature`
        got the configured allowlist. A misspelling that grants more permission
        than the real name is the worst possible direction for a guard to fail.
        Found by Copilot, PR #5.
        """
        # An ENTIRELY unconfigured gate stays off -- nobody opted in, and
        # locking every tenant out of a feature they never enabled is its own
        # failure. That is different from a CONFIGURED gate that does not
        # mention this tenant, which is the fail-open case below.
        if not self.interfaceai_allowed_capabilities.strip():
            return None
        known: list[str] = []
        for entry in self.interfaceai_allowed_capabilities.split(";"):
            name, _, names = entry.partition("=")
            known.append(name.strip())
            if name.strip() != tenant:
                continue
            if names.strip() == "*":
                return None
            return frozenset(n.strip() for n in names.split(",") if n.strip())
        raise ValueError(
            f"tenant {tenant!r} has no capability policy; configured: "
            f"{sorted(n for n in known if n)}. Refusing rather than running unrestricted."
        )

    def confirm_money_above(self, tenant: str) -> Decimal | None:
        """The amount at or above which this tenant wants a person to look.

        None means the tenant configured no threshold, which is a decision.

        ⛔ A MALFORMED THRESHOLD IS AN ERROR, NOT A MISSING ONE. This used to
        swallow `InvalidOperation` and return None, so `baseline=lots` -- or a
        stray character -- silently DISABLED the money guardrail while the
        config file still looked like it had one. Negative and non-finite are
        refused for the same reason. Found by Copilot, PR #5.
        """
        for pair in self.interfaceai_confirm_money_above.split(","):
            name, _, amount = pair.partition("=")
            if name.strip() != tenant:
                continue
            # ⚠️ `baseline=` -- the tenant NAMED with no amount -- used to fall
            # through this loop and return None, silently disabling the money
            # guardrail. Same fail-open as `baseline=lots`, one character
            # shorter, and it survived the first fix. A tenant that appears in
            # the policy has asked for a threshold; an empty one is malformed,
            # not absent. Copilot, PR #5 second pass.
            if not amount.strip():
                raise ValueError(
                    f"confirm_money_above names {tenant!r} with no amount. Remove the entry to "
                    "mean 'no threshold', or give it one -- an empty value silently gates nothing."
                )
            try:
                parsed = Decimal(amount.strip())
            except InvalidOperation as exc:
                raise ValueError(
                    f"confirm_money_above for {tenant!r} is {amount.strip()!r}, which is not a "
                    "number. Refusing to start with a money guardrail that silently does nothing."
                ) from exc
            if not parsed.is_finite() or parsed < 0:
                raise ValueError(
                    f"confirm_money_above for {tenant!r} is {parsed}, which cannot gate anything."
                )
            return parsed
        return None

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return tuple(
            o.strip().rstrip("/") for o in self.interfaceai_allowed_origins.split(",") if o.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
