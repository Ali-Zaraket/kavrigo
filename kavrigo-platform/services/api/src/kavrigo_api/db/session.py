"""Database sessions, with tenant scoping applied at the connection level.

Every tenant-scoped query runs inside a transaction where ``kavrigo.workspace_id`` has been set,
which is what the row-level security policies key on. The important consequence: a repository
method that forgets its ``WHERE workspace_id = ...`` predicate returns *nothing*, not another
tenant's rows.

Two session flavours exist, and the distinction is deliberate:

* :meth:`Database.workspace_session` — the normal path. RLS is active and scoped.
* :meth:`Database.global_session` — for the small set of operations that legitimately span
  workspaces (resolving a user from an identity token, listing a user's memberships, creating a
  workspace). These touch only tables that are *not* tenant-scoped, or filter explicitly by
  ``user_id``. Using it for tenant data would bypass the safety net, so it is named to make that
  obvious in review.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Self

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from kavrigo_api.logging import get_logger

__all__ = ["USER_SETTING", "WORKSPACE_SETTING", "Database"]

_log = get_logger(__name__)

WORKSPACE_SETTING = "kavrigo.workspace_id"
"""The PostgreSQL session variable the tenant-isolation policies read."""

USER_SETTING = "kavrigo.user_id"
"""Set for the one pre-workspace read path: listing the caller's own memberships."""


class Database:
    """Owns the engine and hands out correctly scoped sessions."""

    def __init__(self, dsn: str, *, echo: bool = False, pool_size: int = 10) -> None:
        self._engine: AsyncEngine = create_async_engine(
            dsn,
            echo=echo,
            pool_size=pool_size,
            max_overflow=5,
            pool_pre_ping=True,
            # Statements are never built by string concatenation; asyncpg's prepared-statement
            # cache is left at its default because the schema is stable.
        )
        self._sessionmaker = async_sessionmaker(
            self._engine, expire_on_commit=False, autoflush=False
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    async def dispose(self) -> None:
        await self._engine.dispose()

    async def ping(self) -> bool:
        """Cheap readiness probe. Returns False rather than raising."""
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            _log.warning("database_ping_failed", error_type=type(exc).__name__)
            return False
        return True

    @asynccontextmanager
    async def workspace_session(self, workspace_id: str) -> AsyncIterator[AsyncSession]:
        """A transaction scoped to one workspace, with RLS active.

        ``set_config(..., is_local => true)`` binds the setting to this transaction, so a pooled
        connection cannot leak a previous request's workspace into the next one — which would be
        a cross-tenant read.
        """
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": WORKSPACE_SETTING, "value": workspace_id},
            )
            yield session

    @asynccontextmanager
    async def global_session(self, *, user_id: str | None = None) -> AsyncIterator[AsyncSession]:
        """A transaction with no workspace scope.

        Only for tables that are not tenant-scoped (``users``, ``workspaces``) or for the one
        pre-workspace read path: listing the caller's own memberships, which necessarily happens
        before a workspace has been chosen. Passing ``user_id`` enables the ``memberships_self_read``
        policy, which is SELECT-only and restricted to that user's own rows.

        With neither setting present, RLS still applies to tenant-scoped tables and they return
        no rows — a fail-closed default rather than a leak.
        """
        async with self._sessionmaker() as session, session.begin():
            if user_id is not None:
                await session.execute(
                    text("SELECT set_config(:name, :value, true)"),
                    {"name": USER_SETTING, "value": user_id},
                )
            yield session

    @classmethod
    def from_dsn(cls, dsn: str, **kwargs: object) -> Self:
        return cls(dsn, **kwargs)  # type: ignore[arg-type]


async def set_workspace_scope(session: AsyncSession, workspace_id: str) -> None:
    """Scope an already-open transaction to a workspace.

    Needed for exactly one bootstrap case: creating a workspace and its first membership. The
    workspace row is not tenant-scoped, but the membership row is, and its RLS ``WITH CHECK``
    clause rejects the insert unless the setting is present — which it cannot be beforehand,
    because the workspace did not exist.

    Everywhere else, use :meth:`Database.workspace_session`.
    """
    await session.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": WORKSPACE_SETTING, "value": workspace_id},
    )


async def current_workspace_setting(session: AsyncSession) -> str | None:
    """Read back the workspace the session is scoped to. Used by isolation tests."""
    result = await session.execute(
        text("SELECT current_setting(:name, true)"), {"name": WORKSPACE_SETTING}
    )
    value = result.scalar_one_or_none()
    return value or None
