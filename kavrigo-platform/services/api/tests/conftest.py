"""Integration-test fixtures.

Integration tests require the local PostgreSQL from ``make up`` with migrations applied
(``make migrate``). They are marked ``integration`` and skip cleanly when no database is
reachable, so ``make test`` stays runnable with nothing but Python installed.

Two connections are used on purpose:

* **owner** — creates and truncates tables during setup. Never used by the code under test.
* **application** — the ``kavrigo_app`` role: not a superuser, not the table owner, without
  BYPASSRLS. This is what the API uses, and it is the only way an RLS test means anything.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from kavrigo_api.db.session import Database

APP_DSN = os.getenv(
    "TEST_POSTGRES_DSN",
    "postgresql+asyncpg://kavrigo_app:kavrigo_local_dev@localhost:55432/kavrigo_test",
)
OWNER_DSN = os.getenv(
    "TEST_POSTGRES_OWNER_DSN",
    "postgresql+asyncpg://kavrigo:kavrigo_local_dev@localhost:55432/kavrigo_test",
)

_TABLES = (
    "audit_events",
    "idempotency_keys",
    "agent_versions",
    "agents",
    "memberships",
    "workspaces",
    "users",
)


async def _database_ready(dsn: str) -> bool:
    engine = create_async_engine(dsn, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1 FROM kavrigo.workspaces LIMIT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def integration_available() -> bool:
    return asyncio.run(_database_ready(APP_DSN))


@pytest.fixture
def require_database(integration_available: bool) -> None:
    if not integration_available:
        pytest.skip("no migrated PostgreSQL at TEST_POSTGRES_DSN; run `make up && make migrate`")


@pytest.fixture
async def clean_database(require_database: None) -> AsyncIterator[None]:
    """Truncate every table before each test, as the owner.

    TRUNCATE is deliberately not granted to the application role — it must not be able to erase
    an audit trail — so cleanup uses the owner connection.
    """
    engine = create_async_engine(OWNER_DSN)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("TRUNCATE " + ", ".join(f"kavrigo.{t}" for t in _TABLES) + " CASCADE")
            )
        yield
    finally:
        await engine.dispose()


@pytest.fixture
async def database(clean_database: None) -> AsyncIterator[Database]:
    """A :class:`Database` connected as the least-privilege application role."""
    db = Database(APP_DSN)
    try:
        yield db
    finally:
        await db.dispose()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def pytest_collection_modifyitems(items: Iterator[pytest.Item]) -> None:
    """Mark everything in the integration module so ``-m integration`` selects it."""
    for item in items:
        if "test_integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
