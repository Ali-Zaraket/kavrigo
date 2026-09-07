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


async def _truncate(client: httpx.AsyncClient, table: str, *, attempts: int = 20) -> None:
    """Truncate a table and wait until it actually reads as empty.

    TRUNCATE on a MergeTree drops parts, and a read issued immediately afterwards has been
    observed to still see rows. That produced a suite which passed in isolation and failed
    intermittently in a full run — the worst kind of test, because it teaches people to re-run
    until green. Confirming the post-condition removes the race whatever its cause.
    """
    qualified = f"{CLICKHOUSE_DATABASE}.{table}"
    await client.post(
        CLICKHOUSE_URL, params={"query": f"TRUNCATE TABLE IF EXISTS {qualified}"}, headers=_HEADERS
    )
    for _ in range(attempts):
        response = await client.post(
            CLICKHOUSE_URL,
            params={"query": f"SELECT count() FROM {qualified}"},
            headers=_HEADERS,
        )
        if response.status_code == 200 and response.text.strip() == "0":
            return
        await asyncio.sleep(0.05)
    raise RuntimeError(f"{qualified} did not become empty after TRUNCATE; tests cannot isolate")


@pytest.fixture
async def clickhouse_client(require_clickhouse: None) -> AsyncIterator[httpx.AsyncClient]:
    """A client with the market tables verified empty, so each test starts from a known state."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        for table in ("market_trades", "market_quotes", "market_candles"):
            await _truncate(client, table)
        yield client


def pytest_collection_modifyitems(items: Iterator[pytest.Item]) -> None:
    for item in items:
        if "test_integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
