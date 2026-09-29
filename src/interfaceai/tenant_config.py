"""One institution's deployment, in one reviewable file.

⚠️ WHY A PATH AND NOT A PROFILE NAME. A capability is addressed by NAME because
a filename is storage layout a caller should not know. A TENANT CONFIG is the
opposite case: it carries permissions and a money threshold, so the command
line naming the exact file that granted them is the point. `--tenant-config
tenant_configs/bank_a.yaml` is auditable in a way `--profile bank_a` is not.

⚠️ AND IT IS ADDITIVE. `.env` remains the default for a plain `--tenant
feature`. This is the shape a real deployment ships; the env vars are the shape
a demo ships, and deleting them would break every command in the README to
prove a point.

`docs/layering.md`: a tenant IS a config plus a control map, and nothing else.
This file is the first half.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml
from pydantic import Field, model_validator

from interfaceai.contracts import Contract


class TenantConfig(Contract):
    """Everything that differs between two institutions running the same app."""

    tenant: str = Field(min_length=1)
    app: str = Field(min_length=1)
    base_url: str = Field(min_length=1)

    # A money amount at or above which a person must confirm, whatever control
    # it is typed into. None means this tenant set no threshold, which is a
    # decision. An unparseable one is an ERROR -- see the validator.
    confirm_money_above: Decimal | None = None

    # Which capabilities this tenant may run. `["*"]` means unrestricted.
    # ⚠️ An EMPTY list means "nothing", not "everything". A permissions field
    # whose empty value grants access is how a typo becomes an outage in the
    # permissive direction.
    permits: tuple[str, ...] = ()

    # Where this tenant's pixels live. Relative to the repo root.
    control_maps: str = "control_maps"

    @model_validator(mode="after")
    def _threshold_is_usable(self) -> TenantConfig:
        if self.confirm_money_above is None:
            return self
        if not self.confirm_money_above.is_finite() or self.confirm_money_above < 0:
            raise ValueError(
                f"{self.tenant}: confirm_money_above is {self.confirm_money_above}, "
                "which cannot gate anything. Remove the key to mean 'no threshold'."
            )
        return self

    @property
    def permitted(self) -> frozenset[str] | None:
        """The allowlist replay enforces. None means unrestricted."""
        return None if "*" in self.permits else frozenset(self.permits)


def load_tenant_config(path: Path) -> TenantConfig:
    """Read one tenant's deployment config.

    ⚠️ A malformed file is an ERROR, never a default. The same rule as the
    env-var path, learned the same way: `baseline=lots` silently disabled a
    money guardrail while the config still looked like it had one.
    """
    try:
        raw = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise ValueError(f"cannot read tenant config {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"tenant config {path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(  # noqa: TRY004 -- a bad config file is a config error, not a type error
            f"tenant config {path} must be a mapping, got {type(raw).__name__}"
        )
    if "confirm_money_above" in raw and raw["confirm_money_above"] is not None:
        try:
            raw["confirm_money_above"] = Decimal(str(raw["confirm_money_above"]))
        except InvalidOperation as exc:
            raise ValueError(
                f"{path}: confirm_money_above is {raw['confirm_money_above']!r}, not a number. "
                "Refusing to start with a money guardrail that silently does nothing."
            ) from exc
    return TenantConfig.model_validate(raw)
