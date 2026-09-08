"""Fixtures for ingestion tests.

Integration tests need the local ClickHouse from ``make up``; they skip cleanly when it is not
reachable, so ``make test`` stays runnable with nothing but Python installed.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest

CLICKHOUSE_URL = os.getenv("TEST_CLICKHOUSE_URL", "http://localhost:58123")
CLICKHOUSE_USER = os.getenv("TEST_CLICKHOUSE_USER", "kavrigo")
CLICKHOUSE_PASSWORD = os.getenv("TEST_CLICKHOUSE_PASSWORD", "kavrigo_local_dev")
CLICKHOUSE_DATABASE = os.getenv("TEST_CLICKHOUSE_DATABASE", "kavrigo")

_HEADERS = {"X-ClickHouse-User": CLICKHOUSE_USER, "X-ClickHouse-Key": CLICKHOUSE_PASSWORD}


#: Every table the integration tests touch. All of them must exist before the suite runs.
_REQUIRED_TABLES = ("market_trades", "market_quotes", "market_candles")


async def _clickhouse_ready() -> bool:
    """Whether ClickHouse is up *and* fully initialised.

    Checking a single table is not enough: the server answers ``/ping`` before its
    ``docker-entrypoint-initdb.d`` scripts have finished, so a probe on the first table in the
    schema file can succeed while later tables do not exist yet. That produces a suite that
    half-runs and fails on a missing table instead of skipping cleanly.
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            for table in _REQUIRED_TABLES:
                response = await client.post(
                    CLICKHOUSE_URL,
                    params={"query": f"SELECT 1 FROM {CLICKHOUSE_DATABASE}.{table} LIMIT 1"},
                    headers=_HEADERS,
                )
                if response.status_code != 200:
                    return False
        return True
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="session")
def clickhouse_available() -> bool:
    return asyncio.run(_clickhouse_ready())


@pytest.fixture
def require_clickhouse(clickhouse_available: bool) -> None:
    if not clickhouse_available:
        pytest.skip(
            "no migrated ClickHouse at TEST_CLICKHOUSE_URL; run `make up` "
            "(schema is applied by the container's init scripts)"
        )


@pytest.fixture
def provider_tag() -> str:
    """A discriminator unique to this test, written into every row it inserts.

    Tests used to truncate the shared market tables between cases. That isolates a test from its
    predecessors but not from a *concurrent* run — two pytest processes against the same
    ClickHouse deleted each other's rows, which is what produced a suite that passed alone and
    failed intermittently otherwise. Tagging rows and filtering every assertion removes the
    shared mutable state instead of trying to sequence access to it, so concurrent runs and CI
    re-runs are both safe, and nothing has to be deleted.
    """
    return f"test-{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def clickhouse_client(require_clickhouse: None) -> AsyncIterator[httpx.AsyncClient]:
    """A plain client. Isolation comes from `provider_tag`, not from deleting rows."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        yield client


def pytest_collection_modifyitems(items: Iterator[pytest.Item]) -> None:
    for item in items:
        if "test_integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
