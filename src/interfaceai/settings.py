"""Configuration, loaded from .env (config) and .secret (credentials).

Split follows the nobsmed-v2 convention: .env is committed and holds URLs and
flags, .secret is gitignored and holds anything that would be a finding in a
bank's security review.
"""

from __future__ import annotations

import os
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

    # --- Model access ---
    # Read from .secret, which is NOT the process environment -- so it has to be
    # handed to the SDK explicitly. A key sitting in .secret while the SDK reads
    # os.environ is a silent AuthenticationError at the worst moment.
    anthropic_api_key: SecretStr | None = None

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

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return tuple(
            o.strip().rstrip("/") for o in self.interfaceai_allowed_origins.split(",") if o.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
