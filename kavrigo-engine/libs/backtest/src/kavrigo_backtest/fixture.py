"""Small immutable bar fixtures for deterministic backtest integration.

This is deliberately bounded inline data, not a production historical-data loader. It lets the
adapter and durable workflow execute a meaningful, reproducible BTC or ETH reference run while
the licensed Parquet/catalog path remains a separate data-engineering slice.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from kavrigo_domain import (
    DomainModel,
    ExactDecimal,
    InstrumentId,
    Money,
    UtcDatetime,
    content_hash,
)

__all__ = [
    "BacktestBar",
    "InlineBarDataset",
    "LongOnlyEmaStrategy",
    "bar_dataset_hash",
]


class BacktestBar(DomainModel):
    """One closed OHLCV bar with point-in-time availability."""

    instrument_id: InstrumentId
    interval_seconds: Annotated[int, Field(strict=True, ge=60, le=86_400)]
    open: Annotated[ExactDecimal, Field(gt=0)]
    high: Annotated[ExactDecimal, Field(gt=0)]
    low: Annotated[ExactDecimal, Field(gt=0)]
    close: Annotated[ExactDecimal, Field(gt=0)]
    volume: Annotated[ExactDecimal, Field(gt=0)]
    event_time: UtcDatetime
    ingested_at: UtcDatetime

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("bar OHLC values are inconsistent")
        if self.high < self.low:
            raise ValueError("bar high precedes low")
        if self.ingested_at < self.event_time:
            raise ValueError("bar ingestion precedes its event time")
        return self


def bar_dataset_hash(bars: tuple[BacktestBar, ...]) -> str:
    return content_hash({"format": "inline-bars-v1", "bars": bars})


class InlineBarDataset(DomainModel):
    """A bounded immutable fixture whose hash must appear in the dataset manifest."""

    format: Literal["inline-bars-v1"] = "inline-bars-v1"
    bars: Annotated[tuple[BacktestBar, ...], Field(min_length=12, max_length=5_000)]
    content_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def _integrity(self) -> Self:
        if bar_dataset_hash(self.bars) != self.content_hash:
            raise ValueError("inline bar dataset content hash mismatch")
        event_order = tuple((bar.event_time, bar.instrument_id.value) for bar in self.bars)
        replay_order = tuple((bar.ingested_at, bar.event_time) for bar in self.bars)
        if (
            event_order != tuple(sorted(event_order))
            or replay_order != tuple(sorted(replay_order))
            or len(event_order) != len(set(event_order))
        ):
            raise ValueError("inline bars must be unique and ordered by event and ingestion time")
        return self


class LongOnlyEmaStrategy(DomainModel):
    """Internal diagnostic strategy; never user code and never activation evidence by itself."""

    kind: Literal["long_only_ema_v1"] = "long_only_ema_v1"
    fast_period: Annotated[int, Field(strict=True, ge=2, le=100)] = 3
    slow_period: Annotated[int, Field(strict=True, ge=3, le=500)] = 8
    trade_notional: Money
    price_precision: Annotated[int, Field(strict=True, ge=0, le=12)] = 2
    size_precision: Annotated[int, Field(strict=True, ge=0, le=12)] = 6
    price_increment: Annotated[ExactDecimal, Field(gt=0)] = Decimal("0.01")
    size_increment: Annotated[ExactDecimal, Field(gt=0)] = Decimal("0.000001")

    @model_validator(mode="after")
    def _parameters(self) -> Self:
        if self.fast_period >= self.slow_period:
            raise ValueError("fast EMA period must be below slow EMA period")
        if self.trade_notional.amount <= 0:
            raise ValueError("reference strategy trade notional must be positive")
        price_quantum = Decimal(1).scaleb(-self.price_precision)
        size_quantum = Decimal(1).scaleb(-self.size_precision)
        if self.price_increment.quantize(price_quantum) != self.price_increment:
            raise ValueError("price increment exceeds configured precision")
        if self.size_increment.quantize(size_quantum) != self.size_increment:
            raise ValueError("size increment exceeds configured precision")
        return self
