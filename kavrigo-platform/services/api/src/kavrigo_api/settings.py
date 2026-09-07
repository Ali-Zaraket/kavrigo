"""Control-plane settings.

The safety flags are not ordinary configuration. ``LIVE_TRADING_ENABLED`` defaults to false and
the application refuses to start if it is true, because the gate it would open — legal review,
data licensing, identity/jurisdiction controls, credential isolation, reconciliation, fencing,
kill switches (``MASTER_BUILD_SPEC.md`` §47) — is not built. A flag that silently enables an
unbuilt capability is worse than no flag.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings"]


class Settings(BaseSettings):
    """Environment-driven settings. See `.env.example` for the full documented set."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # --- Safety gate ------------------------------------------------------
    live_trading_enabled: bool = False
    default_trading_mode: Literal["paper", "backtest", "research"] = "paper"

    # --- Service ----------------------------------------------------------
    kavrigo_env: Literal["local", "dev", "staging", "paper-prod", "live-prod"] = "local"
    api_host: str = "0.0.0.0"  # noqa: S104 - bound inside the container, not exposed directly
    api_port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"
    service_name: str = "kavrigo-api"
    git_sha: str = "unknown"
    container_image_digest: str = "unknown"

    # --- Identity (ADR: Clerk for product authentication) -----------------
    # Clerk issues standard JWTs, so the verifier is configured with an issuer and JWKS URL
    # rather than coded against vendor-specific endpoints. Confirm these values and the claim
    # names against current Clerk documentation before the first real token is verified.
    auth_provider: Literal["dev", "jwks"] = "dev"
    auth_issuer: str | None = None
    auth_jwks_url: str | None = None
    auth_audience: str | None = None
    auth_organization_claim: str = "org_id"
    auth_mfa_claim: str = "mfa"

    # --- Infrastructure ---------------------------------------------------
    postgres_dsn: str | None = None
    clickhouse_url: str | None = None
    redpanda_bootstrap_servers: str | None = None
    valkey_url: str | None = None
    temporal_address: str | None = None

    @model_validator(mode="after")
    def _enforce_live_gate(self) -> Self:
        if self.live_trading_enabled:
            raise ValueError(
                "LIVE_TRADING_ENABLED=true is refused. Live execution requires the readiness "
                "checklist in MASTER_BUILD_SPEC.md §47 — legal review, data-licence rights, "
                "identity/jurisdiction controls, credential isolation, reconciliation, fencing "
                "and kill switches — none of which is implemented. See ADR 0001."
            )
        if self.kavrigo_env == "live-prod":
            raise ValueError("the live-prod environment does not exist yet (ADR 0001)")
        return self

    @model_validator(mode="after")
    def _enforce_auth_configuration(self) -> Self:
        """Refuse a development authentication bypass outside local development.

        ``DevIdentityProvider`` accepts unsigned ``dev:<subject>`` tokens. Reachable in a
        deployed environment that is not an inconvenience, it is an authentication bypass — so
        the process refuses to start rather than serving with it enabled.
        """
        if self.auth_provider == "dev" and self.kavrigo_env != "local":
            raise ValueError(
                f"AUTH_PROVIDER=dev is refused in the {self.kavrigo_env} environment; "
                "it accepts unsigned tokens and is for local development only"
            )
        if self.auth_provider == "jwks":
            missing = [
                name
                for name, value in (
                    ("AUTH_ISSUER", self.auth_issuer),
                    ("AUTH_JWKS_URL", self.auth_jwks_url),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"AUTH_PROVIDER=jwks requires {', '.join(missing)}")
        return self

    @property
    def is_production_like(self) -> bool:
        return self.kavrigo_env in {"staging", "paper-prod", "live-prod"}


_settings: Settings | None = None


def get_settings() -> Settings:
    """Process-wide settings, resolved once.

    Deliberately not cached with ``lru_cache`` so tests can reset it explicitly rather than
    fighting a cache that outlives a monkeypatched environment.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_cache() -> None:
    """Test hook: forget the resolved settings."""
    global _settings
    _settings = None
