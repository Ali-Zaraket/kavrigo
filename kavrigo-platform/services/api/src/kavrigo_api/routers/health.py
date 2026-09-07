"""Health, readiness and platform-mode endpoints.

``/healthz`` answers "is this process alive". ``/readyz`` answers "should traffic be routed
here" and is where dependency checks will live once there are dependencies. They are separate
because conflating them causes a pod to be killed for a transient database blip.

``/v1/platform/mode`` exists so the web client can render paper/live status from the server's
authoritative view rather than its own build-time constant. Paper and live must be impossible to
confuse (``MASTER_BUILD_SPEC.md`` §31), and that guarantee cannot rest on the frontend.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from kavrigo_api.db.session import Database
from kavrigo_api.settings import Settings, get_settings

router = APIRouter(tags=["platform"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    checks: dict[str, Literal["ok", "unavailable", "not_configured"]]


class PlatformModeResponse(BaseModel):
    """The authoritative trading-mode state for the whole platform."""

    live_trading_enabled: Literal[False] = Field(
        default=False,
        description=(
            "Always false in this release. Live execution is gated on MASTER_BUILD_SPEC.md §47 "
            "and ADR 0001."
        ),
    )
    default_trading_mode: str
    environment: str
    disclosure: str


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
async def healthz(settings: SettingsDep) -> HealthResponse:
    from kavrigo_api import __version__

    return HealthResponse(status="ok", service=settings.service_name, version=__version__)


@router.get("/readyz", response_model=ReadinessResponse, summary="Readiness probe")
async def readyz(request: Request, settings: SettingsDep) -> ReadinessResponse:
    # Probes are added as each dependency is wired in. Reporting "not_configured" rather than
    # "ok" keeps this endpoint honest about what has actually been checked.
    checks: dict[str, Literal["ok", "unavailable", "not_configured"]] = {
        "clickhouse": "ok" if settings.clickhouse_url else "not_configured",
        "redpanda": "ok" if settings.redpanda_bootstrap_servers else "not_configured",
        "temporal": "ok" if settings.temporal_address else "not_configured",
    }

    database: Database | None = getattr(request.app.state, "database", None)
    if database is None:
        checks["postgres"] = "not_configured"
    else:
        checks["postgres"] = "ok" if await database.ping() else "unavailable"

    # The control plane cannot serve authenticated requests without its database, so an
    # unreachable database is "degraded" and should take the pod out of rotation.
    degraded = any(state == "unavailable" for state in checks.values())
    return ReadinessResponse(status="degraded" if degraded else "ready", checks=checks)


@router.get(
    "/v1/platform/mode",
    response_model=PlatformModeResponse,
    summary="Authoritative trading-mode state",
)
async def platform_mode(settings: SettingsDep) -> PlatformModeResponse:
    return PlatformModeResponse(
        default_trading_mode=settings.default_trading_mode,
        environment=settings.kavrigo_env,
        disclosure=(
            "Simulated results only. Paper trading and backtests use real market data with "
            "simulated orders and fills; they are not live results and are not a prediction of "
            "future performance."
        ),
    )
