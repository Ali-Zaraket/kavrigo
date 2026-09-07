"""Fixtures for ingestion tests.

Integration tests need the local ClickHouse from ``make up``; they skip cleanly when it is not
reachable, so ``make test`` stays runnable with nothing but Python installed.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest

CLICKHOUSE_URL = os.getenv("TEST_CLICKHOUSE_URL", "http://localhost:58123")
CLICKHOUSE_USER = os.getenv("TEST_CLICKHOUSE_USER", "kavrigo")
CLICKHOUSE_PASSWORD = os.getenv("TEST_CLICKHOUSE_PASSWORD", "kavrigo_local_dev")
CLICKHOUSE_DATABASE = os.getenv("TEST_CLICKHOUSE_DATABASE", "kavrigo")

_HEADERS = {"X-ClickHouse-User": CLICKHOUSE_USER, "X-ClickHouse-Key": CLICKHOUSE_PASSWORD}


async def _clickhouse_ready() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(
                CLICKHOUSE_URL,
                params={"query": f"SELECT 1 FROM {CLICKHOUSE_DATABASE}.market_trades LIMIT 1"},
                headers=_HEADERS,
            )
        return response.status_code == 200
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
async def clickhouse_client(require_clickhouse: None) -> AsyncIterator[httpx.AsyncClient]:
    """A client with the market tables truncated, so each test starts from a known state."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        for table in ("market_trades", "market_quotes", "market_candles"):
            await client.post(
                CLICKHOUSE_URL,
                params={"query": f"TRUNCATE TABLE IF EXISTS {CLICKHOUSE_DATABASE}.{table}"},
                headers=_HEADERS,
            )
        yield client


def pytest_collection_modifyitems(items: Iterator[pytest.Item]) -> None:
    for item in items:
        if "test_integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
