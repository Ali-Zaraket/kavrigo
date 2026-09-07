"""Kavrigo control-plane application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from kavrigo_api.auth.identity import (
    DevIdentityProvider,
    IdentityProvider,
    JwksIdentityProvider,
)
from kavrigo_api.db.session import Database
from kavrigo_api.errors import install_exception_handlers
from kavrigo_api.logging import configure_logging, get_logger
from kavrigo_api.middleware import RequestContextMiddleware
from kavrigo_api.routers import agents, health, workspaces
from kavrigo_api.settings import Settings, get_settings

__all__ = ["create_app"]

_DESCRIPTION = """
Kavrigo control plane.

Kavrigo is a platform for building, testing and governing AI trading agents. Agents produce
structured, evidence-backed decisions; a deterministic risk engine outside the model decides
whether an order intent is permitted.

**This release is paper and research only.** Live execution is disabled and gated on the
readiness checklist in the master specification. Backtest and paper results are simulations, not
live results, and nothing here is investment advice.
"""


def build_identity_provider(settings: Settings) -> IdentityProvider:
    """Select the identity provider.

    ``Settings`` has already refused ``dev`` outside local development, so reaching that branch
    here means the environment really is local.
    """
    if settings.auth_provider == "dev":
        return DevIdentityProvider()
    assert settings.auth_issuer is not None  # enforced by Settings
    assert settings.auth_jwks_url is not None
    return JwksIdentityProvider(
        issuer=settings.auth_issuer,
        jwks_url=settings.auth_jwks_url,
        audience=settings.auth_audience,
        organization_claim=settings.auth_organization_claim,
        mfa_claim=settings.auth_mfa_claim,
    )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger = get_logger(__name__)
    logger.info(
        "service_starting",
        service=settings.service_name,
        environment=settings.kavrigo_env,
        live_trading_enabled=settings.live_trading_enabled,
        default_trading_mode=settings.default_trading_mode,
        auth_provider=settings.auth_provider,
        git_sha=settings.git_sha,
    )
    try:
        yield
    finally:
        database: Database | None = getattr(app.state, "database", None)
        if database is not None:
            await database.dispose()
        logger.info("service_stopped", service=settings.service_name)


def create_app(
    settings: Settings | None = None,
    *,
    database: Database | None = None,
    identity_provider: IdentityProvider | None = None,
) -> FastAPI:
    """Build the application.

    Settings validation happens before anything else: if ``LIVE_TRADING_ENABLED`` is true, or a
    development authentication bypass is configured outside local development, the process
    refuses to start rather than serving with an unsafe configuration (see ``settings.Settings``).

    ``database`` and ``identity_provider`` are injectable so tests can supply real or fake
    implementations without reaching for module-level globals.
    """
    resolved = settings or get_settings()
    configure_logging(level=resolved.log_level, fmt=resolved.log_format)

    app = FastAPI(
        title="Kavrigo Control Plane",
        version="0.1.0",
        description=_DESCRIPTION,
        lifespan=_lifespan,
        openapi_url="/openapi.json",
        docs_url="/docs" if not resolved.is_production_like else None,
    )
    app.state.settings = resolved
    app.state.database = (
        database
        if database is not None
        else (Database(resolved.postgres_dsn) if resolved.postgres_dsn else None)
    )
    app.state.identity_provider = identity_provider or build_identity_provider(resolved)
    app.dependency_overrides[get_settings] = lambda: resolved

    app.add_middleware(RequestContextMiddleware)
    install_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(workspaces.router)
    app.include_router(agents.router)
    return app
