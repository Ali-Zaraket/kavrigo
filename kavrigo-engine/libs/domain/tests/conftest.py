"""Shared fixtures and factories for domain contract tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from kavrigo_domain import (
    AgentSpec,
    DataPack,
    InstrumentId,
    ModelPolicy,
    ScheduleConfig,
    UniverseConfig,
)
from kavrigo_domain.testing import AS_OF, oid


@pytest.fixture
def btc() -> InstrumentId:
    return InstrumentId.parse("BTC-USDT.BINANCE")


@pytest.fixture
def eth() -> InstrumentId:
    return InstrumentId.parse("ETH-USDT.BINANCE")


@pytest.fixture
def usdt() -> str:
    return "USDT"


@pytest.fixture
def later() -> datetime:
    return AS_OF + timedelta(minutes=5)


@pytest.fixture
def agent_spec(btc: InstrumentId) -> AgentSpec:
    return AgentSpec(
        name="btc-paper-baseline",
        universe=UniverseConfig(instruments=[btc]),
        schedule=ScheduleConfig(decision_interval_seconds=900),
        data_packs=[DataPack.MARKET_MICROSTRUCTURE, DataPack.PRICE_TECHNICAL],
        model_policy=ModelPolicy(max_cost_per_decision_usd=Decimal("0.10")),
        risk_policy_ref=oid("rp"),
        execution_policy_ref=oid("ep"),
    )
