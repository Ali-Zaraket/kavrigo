"""Authenticated, local-only, non-persistent CoinGecko Demo reference preview."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Response
from pydantic import SecretStr

from kavrigo_api.auth.dependencies import WorkspaceDep, require
from kavrigo_api.auth.principal import Permission
from kavrigo_api.errors import ApiError, ErrorCode
from kavrigo_api.schemas.market_preview import DemoMarketPreview
from kavrigo_api.services.coingecko_demo import DemoPriceError, fetch_demo_prices
from kavrigo_api.settings import Settings, get_settings

router = APIRouter(prefix="/v1/workspaces/{workspace_id}", tags=["market-preview"])


@router.get(
    "/market/demo-reference-prices",
    response_model=DemoMarketPreview,
    dependencies=[Depends(require(Permission.WORKSPACE_READ))],
)
async def demo_reference_prices(
    context: WorkspaceDep,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DemoMarketPreview:
    """Show BTC/ETH for a local owner only; never feed trading or durable evidence."""
    del context  # membership and permission were verified by dependencies
    response.headers["Cache-Control"] = "private, no-store"
    if settings.kavrigo_env != "local":
        raise ApiError(ErrorCode.NOT_FOUND, "Market preview is unavailable.", 404)
    key: SecretStr | None = settings.coingecko_api_key
    if key is None or not key.get_secret_value():
        raise ApiError(
            ErrorCode.UPSTREAM_UNAVAILABLE, "Demo market preview is not configured.", 503
        )
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
            return await fetch_demo_prices(
                client, api_key=key.get_secret_value(), fetched_at=datetime.now(UTC)
            )
    except DemoPriceError as exc:
        raise ApiError(
            ErrorCode.UPSTREAM_UNAVAILABLE, "Demo market preview is unavailable.", 503
        ) from exc
