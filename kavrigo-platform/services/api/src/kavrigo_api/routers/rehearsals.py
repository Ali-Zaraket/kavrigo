"""Authenticated local-only rehearsal launch of one immutable paper draft."""

import asyncio
import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, status
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from kavrigo_api.auth.dependencies import WorkspaceSession, require
from kavrigo_api.auth.principal import Permission, WorkspaceContext
from kavrigo_api.errors import ApiError, ErrorCode
from kavrigo_api.logging import get_logger
from kavrigo_api.repositories.agents import AgentRepository
from kavrigo_api.schemas.rehearsals import RehearsalLaunch
from kavrigo_api.services.idempotency import idempotency_key_from
from kavrigo_api.settings import Settings, get_settings
from kavrigo_domain import (
    AgentSpec,
    AgentVersion,
    BookTicker,
    MarketTrade,
    TradingMode,
    content_hash,
)
from kavrigo_market_ingestion import TestnetSampleUnavailable, collect_testnet_sample
from kavrigo_workflows.database import EngineDatabase
from kavrigo_workflows.dispatch import dispatch_run
from kavrigo_workflows.machine import DurableError
from kavrigo_workflows.rehearsal import persist_rehearsal
from kavrigo_workflows.runs import RunRepository

router = APIRouter(prefix="/v1/workspaces/{workspace_id}/agents", tags=["rehearsals"])
_log = get_logger(__name__)
AgentPath = Annotated[str, Path(pattern=r"^ag_[0-9a-f]{32}$")]
VersionPath = Annotated[int, Path(ge=1)]


@router.post(
    "/{agent_id}/versions/{version}/rehearsals",
    response_model=RehearsalLaunch,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Launch an execution-disabled local paper rehearsal",
)
async def launch_rehearsal(
    agent_id: AgentPath,
    version: VersionPath,
    request: Request,
    session: WorkspaceSession,
    context: Annotated[WorkspaceContext, Depends(require(Permission.RUN_START))],
    settings: Annotated[Settings, Depends(get_settings)],
    source: Annotated[Literal["synthetic", "binance_testnet"], Query()] = "synthetic",
) -> RehearsalLaunch:
    if settings.kavrigo_env != "local" or settings.default_trading_mode != "paper":
        raise ApiError(ErrorCode.FORBIDDEN, "Local paper rehearsal is unavailable.", 403)
    if not settings.postgres_dsn:
        raise ApiError(ErrorCode.UPSTREAM_UNAVAILABLE, "Paper engine is unavailable.", 503)
    key = idempotency_key_from(request)
    if key is None or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", key) is None:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "A valid Idempotency-Key is required.", 400)
    agents = AgentRepository(session, context.workspace_id)
    agent = await agents.get_agent(agent_id)
    row = await agents.get_version(agent_id, version)
    if agent is None or row is None or agent.archived_at is not None:
        raise ApiError(ErrorCode.NOT_FOUND, "Agent version not found.", 404)
    spec = AgentSpec.model_validate(row.spec)
    if content_hash(spec) != row.spec_hash or spec.mode is not TradingMode.PAPER:
        raise ApiError(ErrorCode.CONFLICT, "Agent version is not a valid paper draft.", 409)
    frozen = AgentVersion.model_validate(
        {
            "agent_version_id": row.agent_version_id,
            "agent_id": row.agent_id,
            "workspace_id": row.workspace_id,
            "version": row.version,
            "spec": spec,
            "spec_hash": row.spec_hash,
            "prompt_version_id": row.prompt_version_id,
            "prompt_hash": row.prompt_hash,
            "feature_set_version": row.feature_set_version,
            "created_at": row.created_at,
            "created_by": row.created_by,
            "author_kind": row.author_kind,
            "change_summary": row.change_summary,
            "stage": row.stage,
            "approval_status": row.approval_status,
            "approved_environments": row.approved_environments,
        }
    )
    database = EngineDatabase(settings.postgres_dsn)
    try:
        try:
            testnet_events: tuple[MarketTrade | BookTicker, ...] = ()
            if source == "binance_testnet":
                testnet_events = await collect_testnet_sample(
                    tuple(instrument.base for instrument in spec.universe.instruments)
                )
            ref, replayed = await persist_rehearsal(
                database,
                frozen,
                key=key,
                at=datetime.now(UTC),
                testnet_events=testnet_events,
            )
        except TestnetSampleUnavailable as error:
            raise ApiError(
                ErrorCode.UPSTREAM_UNAVAILABLE,
                "Binance Spot Testnet did not provide a complete bounded sample.",
                503,
            ) from error
        except DurableError as error:
            if str(error) == "rehearsal_idempotency_conflict":
                raise ApiError(
                    ErrorCode.IDEMPOTENCY_KEY_REUSED,
                    "This Idempotency-Key belongs to another rehearsal.",
                    409,
                ) from error
            raise
        except ValueError as error:
            if str(error) == "rehearsal_requires_one_or_two_simulated_usd_spot_instruments":
                raise ApiError(
                    ErrorCode.VALIDATION_FAILED,
                    "Rehearsal requires one or two USD spot instruments on SIM.",
                    422,
                ) from error
            if str(error) == "testnet_sample_supports_btc_and_eth_only":
                raise ApiError(
                    ErrorCode.VALIDATION_FAILED,
                    "Binance Spot Testnet rehearsal supports BTC and ETH only.",
                    422,
                ) from error
            raise
        dispatched = False
        if settings.temporal_address:
            try:
                client = await asyncio.wait_for(
                    Client.connect(
                        settings.temporal_address,
                        data_converter=pydantic_data_converter,
                    ),
                    timeout=5,
                )
                await dispatch_run(client, RunRepository(database), ref, "kavrigo-paper-v1")
                dispatched = True
            except Exception as error:
                # The durable outbox remains pending. Same-key retry can dispatch it.
                _log.warning("rehearsal_dispatch_pending", error_type=type(error).__name__)
        _log.info(
            "rehearsal_submitted",
            dispatch_state="dispatched" if dispatched else "queued",
            replayed=replayed,
            source=source,
        )
        return RehearsalLaunch(
            run_id=ref.run_id,
            input_hash=ref.input_hash,
            dispatch_state="dispatched" if dispatched else "queued",
            replayed=replayed,
            input_kind=(
                "testnet_rehearsal" if source == "binance_testnet" else "synthetic_rehearsal"
            ),
        )
    finally:
        await database.close()
