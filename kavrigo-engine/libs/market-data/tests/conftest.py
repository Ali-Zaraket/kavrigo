"""Fixtures for market-data adapter tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from kavrigo_domain import InstrumentId
from kavrigo_marketdata import InstrumentMap

FIXTURES = Path(__file__).parent / "fixtures"
RECEIVED_AT = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def binance_instruments() -> InstrumentMap:
    """Only BTC and ETH are subscribed; DOGEUSDT appears in the fixture and must be dropped."""
    return InstrumentMap(
        {
            "BTCUSDT": InstrumentId.parse("BTC-USDT.BINANCE"),
            "ETHUSDT": InstrumentId.parse("ETH-USDT.BINANCE"),
        }
    )


@pytest.fixture
def coinbase_instruments() -> InstrumentMap:
    return InstrumentMap({"BTC-USD": InstrumentId.parse("BTC-USD.COINBASE")})
