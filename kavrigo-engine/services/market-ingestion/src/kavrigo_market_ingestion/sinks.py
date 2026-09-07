"""Where normalized events go.

Two sinks exist today: an in-memory one for tests, and ClickHouse for the analytical store
(ADR 0008). The Redpanda producer is a separate slice — the sink interface is what keeps that
addition from rippling through the pipeline.

ClickHouse notes that are easy to get wrong:

* **Decimals are sent as strings.** ``Decimal(38, 18)`` accepts both, but a JSON number would be
  parsed as a double on the way in and lose precision — the exact defect the domain's decimal
  types exist to prevent.
* **Timestamps use ``YYYY-MM-DD hh:mm:ss.mmm``.** For ``DateTime64(3)`` a bare number is
  interpreted differently across ClickHouse versions, so the unambiguous textual form is used.
* **Inserts are idempotent only by de-duplication upstream.** ClickHouse ``MergeTree`` will
  happily store a row twice, so at-least-once delivery must be de-duplicated before it gets
  here, or accepted as double-counted. Sequence handling in ``StreamHealthMonitor`` is what
  drops duplicates before this point.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

import httpx

from kavrigo_domain import BookTicker, Candle, MarketTrade
from kavrigo_marketdata import MarketEvent

__all__ = ["ClickHouseSink", "EventSink", "MemorySink", "clickhouse_rows_for"]

_TABLES = {
    MarketTrade: "market_trades",
    BookTicker: "market_quotes",
    Candle: "market_candles",
}


def _ts(value: datetime | None) -> str | None:
    """Format for ``DateTime64(3, 'UTC')``, in the one representation every version agrees on."""
    if value is None:
        return None
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.") + f"{value.microsecond // 1000:03d}"


def _dec(value: Decimal | None) -> str | None:
    """Decimals cross the wire as strings so nothing is routed through a double."""
    return None if value is None else format(value, "f")


@runtime_checkable
class EventSink(Protocol):
    """Accepts batches of normalized events."""

    async def write(self, events: Sequence[MarketEvent], *, ingested_at: datetime) -> int: ...
    async def close(self) -> None: ...


class MemorySink:
    """Collects events in memory. For tests and for running the pipeline with no dependencies."""

    def __init__(self) -> None:
        self.events: list[MarketEvent] = []
        self.batches: list[int] = []

    async def write(self, events: Sequence[MarketEvent], *, ingested_at: datetime) -> int:
        self.events.extend(events)
        self.batches.append(len(events))
        return len(events)

    async def close(self) -> None:
        return None


def clickhouse_rows_for(
    event: MarketEvent, *, provider: str, ingested_at: datetime
) -> tuple[str, dict[str, Any]]:
    """Render one event as (table, row) for ``JSONEachRow`` insertion."""
    instrument = event.instrument_id
    common: dict[str, Any] = {
        "venue": instrument.venue,
        "instrument_id": instrument.value,
        "ingested_at": _ts(ingested_at),
        "provider": provider,
        "schema_version": "1",
    }

    if isinstance(event, MarketTrade):
        return "market_trades", {
            **common,
            "event_time": _ts(event.venue_time),
            "price": _dec(event.price.value),
            "quantity": _dec(event.quantity.value),
            "aggressor": event.aggressor.value,
            "venue_trade_id": event.venue_trade_id or "",
            "sequence": event.sequence if event.sequence is not None else 0,
        }

    if isinstance(event, BookTicker):
        return "market_quotes", {
            **common,
            # bookTicker has no venue timestamp; arrival time is the only honest event time.
            "event_time": _ts(event.venue_time or event.received_at),
            "has_venue_time": 1 if event.venue_time is not None else 0,
            "bid_price": _dec(event.bid_price.value),
            "bid_size": _dec(event.bid_size.value),
            "ask_price": _dec(event.ask_price.value),
            "ask_size": _dec(event.ask_size.value),
            "spread_bps": _dec(event.spread_bps),
            "sequence": event.sequence if event.sequence is not None else 0,
        }

    if isinstance(event, Candle):
        return "market_candles", {
            **common,
            "event_time": _ts(event.close_time),
            "interval": event.interval,
            "open_time": _ts(event.open_time),
            "close_time": _ts(event.close_time),
            "open": _dec(event.open),
            "high": _dec(event.high),
            "low": _dec(event.low),
            "close": _dec(event.close),
            "volume": _dec(event.volume),
            "quote_volume": _dec(event.quote_volume) or "0",
            "taker_buy_base_volume": _dec(event.taker_buy_base_volume) or "0",
            "trade_count": event.trade_count or 0,
            # Carried, never assumed: an unclosed bar consumed as final is look-ahead bias.
            "is_closed": 1 if event.is_closed else 0,
        }

    raise TypeError(f"no ClickHouse mapping for {type(event).__name__}")  # pragma: no cover


class ClickHouseSink:
    """Writes normalized events to ClickHouse over the HTTP interface."""

    def __init__(
        self,
        url: str,
        *,
        database: str = "kavrigo",
        user: str | None = None,
        password: str | None = None,
        provider: str = "unknown",
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._database = database
        self._provider = provider
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._headers: dict[str, str] = {}
        if user is not None:
            self._headers["X-ClickHouse-User"] = user
        if password is not None:
            self._headers["X-ClickHouse-Key"] = password

    async def write(self, events: Sequence[MarketEvent], *, ingested_at: datetime) -> int:
        if not events:
            return 0

        # Group by table: one INSERT per table beats one per row by orders of magnitude, and
        # ClickHouse is explicitly built for large batched inserts rather than row-at-a-time.
        batches: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            table, row = clickhouse_rows_for(
                event, provider=self._provider, ingested_at=ingested_at
            )
            batches.setdefault(table, []).append(row)

        written = 0
        for table, rows in batches.items():
            await self._insert(table, rows)
            written += len(rows)
        return written

    async def _insert(self, table: str, rows: Sequence[dict[str, Any]]) -> None:
        import orjson

        body = b"\n".join(orjson.dumps(row) for row in rows)
        response = await self._client.post(
            self._url,
            params={
                "query": f"INSERT INTO {self._database}.{table} FORMAT JSONEachRow",
                "database": self._database,
            },
            content=body,
            headers=self._headers,
        )
        if response.status_code >= 400:
            # The response body carries ClickHouse's own diagnostic, which is what makes a
            # schema mismatch debuggable instead of a bare 400.
            raise RuntimeError(
                f"ClickHouse insert into {table} failed ({response.status_code}): "
                f"{response.text[:500]}"
            )

    async def ping(self) -> bool:
        try:
            response = await self._client.get(f"{self._url}/ping", headers=self._headers)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def table_for(event: MarketEvent) -> str:
    return _TABLES[type(event)]
