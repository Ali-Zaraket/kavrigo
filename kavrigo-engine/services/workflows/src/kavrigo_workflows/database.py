"""Shared transaction boundary. The application role must remain subject to forced RLS."""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from kavrigo_domain import DomainModel
from kavrigo_workflows.machine import DurableError

MAX_BYTES = 10_000_000


def encode(value: DomainModel) -> str:
    result = value.model_dump_json(warnings="error")
    if len(result.encode("utf-8")) > MAX_BYTES:
        raise DurableError("artifact_too_large")
    return result


async def row(
    connection: AsyncConnection, sql: str, values: Mapping[str, Any]
) -> RowMapping | None:
    return (await connection.execute(text(sql), values)).mappings().one_or_none()


async def db_now(connection: AsyncConnection) -> datetime:
    value = (await connection.execute(text("SELECT clock_timestamp()"))).scalar_one()
    if not isinstance(value, datetime):
        raise DurableError("invalid_database_clock")
    return value


class EngineDatabase:
    def __init__(self, dsn: str, *, environment: str = "local") -> None:
        if environment != "local":
            raise DurableError("durable_engine_is_local_only")
        self.engine = create_async_engine(dsn, pool_pre_ping=True, pool_size=5, max_overflow=5)

    @asynccontextmanager
    async def transaction(self, workspace_id: str) -> AsyncIterator[AsyncConnection]:
        async with self.engine.begin() as connection:
            await connection.execute(
                text("SELECT set_config('kavrigo.workspace_id', :workspace, true)"),
                {"workspace": workspace_id},
            )
            await connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            await connection.execute(text("SET LOCAL statement_timeout = '15s'"))
            yield connection

    async def close(self) -> None:
        await self.engine.dispose()
