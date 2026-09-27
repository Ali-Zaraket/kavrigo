"""Health, readiness and platform-mode endpoints.

``/healthz`` answers "is this process alive". ``/readyz`` answers "can this control plane
serve tenant requests". They are separate because conflating them causes a pod to be killed for
a transient database blip. PostgreSQL is probed; configured downstream services are explicitly
unverified here, rather than reported healthy from their settings alone.

``/v1/platform/mode`` exists so the web client can render paper/live status from the server's
authoritative view rather than its own build-time constant. Paper and live must be impossible to
confuse (``MASTER_BUILD_SPEC.md`` §31), and that guarantee cannot rest on the frontend.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from kavrigo_api.db.session import Database
from kavrigo_api.logging import get_logger
from kavrigo_api.settings import Settings, get_settings

router = APIRouter(tags=["platform"])
_log = get_logger(__name__)

SettingsDep = Annotated[Settings, Depends(get_settings)]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    checks: dict[str, Literal["ok", "unavailable", "not_configured", "configured_unverified"]]


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


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "Control plane is not ready"}},
    summary="Readiness probe",
)
async def readyz(request: Request, response: Response, settings: SettingsDep) -> ReadinessResponse:
    # A configured address is not a successful dependency probe. Downstream service health
    # belongs to their own supervision; this API's tenant authority is PostgreSQL.
    checks: dict[str, Literal["ok", "unavailable", "not_configured", "configured_unverified"]] = {
        "clickhouse": "configured_unverified" if settings.clickhouse_url else "not_configured",
        "redpanda": (
            "configured_unverified" if settings.redpanda_bootstrap_servers else "not_configured"
        ),
        "temporal": "configured_unverified" if settings.temporal_address else "not_configured",
        "valkey": "configured_unverified" if settings.valkey_url else "not_configured",
    }

    database: Database | None = getattr(request.app.state, "database", None)
    if database is None:
        checks["postgres"] = "not_configured"
    else:
        try:
            checks["postgres"] = (
                "ok" if await asyncio.wait_for(database.ping(), timeout=2) else "unavailable"
            )
        except TimeoutError:
            checks["postgres"] = "unavailable"
            _log.warning("database_readiness_timed_out")

    # The control plane cannot serve authenticated requests without its database, so an
    # unreachable database is "degraded" and should take the pod out of rotation.
    degraded = checks["postgres"] != "ok"
    if degraded:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
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
            "Simulated results only. Current local rehearsals and reference backtests use "
            "synthetic or testnet evidence; inspect each run's source and limitations. "
            "No live market strategy result or real-money execution is represented, and "
            "simulated outcomes do not predict future performance."
        ),
    )
