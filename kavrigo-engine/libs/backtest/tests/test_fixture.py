"""Inline historical fixtures stay point-in-time, bounded and hash-addressed."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from kavrigo_backtest import BacktestBar, InlineBarDataset, bar_dataset_hash
from kavrigo_domain import InstrumentId

AT = datetime(2026, 1, 1, tzinfo=UTC)
BTC = InstrumentId.parse("BTC-USDT.BINANCE")


def _bar(index: int) -> BacktestBar:
    price = Decimal(100 + index)
    return BacktestBar(
        instrument_id=BTC,
        interval_seconds=900,
        open=price,
        high=price + Decimal(1),
        low=price - Decimal(1),
        close=price + Decimal("0.5"),
        volume=Decimal("10.000000"),
        event_time=AT + timedelta(minutes=15 * index),
        ingested_at=AT + timedelta(minutes=15 * index, seconds=1),
    )


def test_fixture_hash_binds_every_bar() -> None:
    bars = tuple(_bar(index) for index in range(12))
    fixture = InlineBarDataset(bars=bars, content_hash=bar_dataset_hash(bars))

    assert fixture.content_hash == bar_dataset_hash(fixture.bars)


def test_tampered_fixture_hash_is_rejected() -> None:
    bars = tuple(_bar(index) for index in range(12))

    with pytest.raises(ValidationError, match="content hash mismatch"):
        InlineBarDataset(bars=bars, content_hash="sha256:" + "0" * 64)


def test_bar_cannot_be_known_before_its_event_time() -> None:
    values = _bar(0).model_dump(mode="python")
    values["ingested_at"] = AT - timedelta(seconds=1)
    with pytest.raises(ValidationError, match="ingestion precedes"):
        BacktestBar.model_validate(values)


def test_fixture_must_be_in_replay_order() -> None:
    bars = tuple(_bar(index) for index in range(12))

    with pytest.raises(ValidationError, match="ordered"):
        InlineBarDataset(
            bars=(bars[1], bars[0], *bars[2:]),
            content_hash=bar_dataset_hash((bars[1], bars[0], *bars[2:])),
        )
