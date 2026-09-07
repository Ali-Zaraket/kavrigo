"""Portfolio accounting invariants."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from kavrigo_domain import (
    InstrumentId,
    Money,
    PortfolioSnapshot,
    Position,
    Price,
    Quantity,
    TradingMode,
)
from kavrigo_domain.testing import AS_OF, oid

BTC = InstrumentId.parse("BTC-USDT.BINANCE")
ETH = InstrumentId.parse("ETH-USDT.BINANCE")


def _usdt(amount: str) -> Money:
    return Money(amount=amount, currency="USDT")


def _position(instrument: InstrumentId = BTC, **overrides: object) -> Position:
    base: dict[str, object] = {
        "instrument_id": instrument,
        "quantity": Quantity(value="0.1", asset=instrument.base),
        "mark_price": Price(value="60000", base=instrument.base, quote=instrument.quote),
        "realized_pnl": _usdt("0"),
        "unrealized_pnl": _usdt("120"),
    }
    return Position(**{**base, **overrides})  # type: ignore[arg-type]


def _portfolio(**overrides: object) -> PortfolioSnapshot:
    base: dict[str, object] = {
        "workspace_id": oid("ws"),
        "mode": TradingMode.PAPER,
        "as_of": AS_OF,
        "base_currency": "USDT",
        "cash": _usdt("4000"),
        "reserved_cash": _usdt("500"),
        "positions": [_position()],
        "realized_pnl_today": _usdt("0"),
        "unrealized_pnl": _usdt("120"),
        "equity": _usdt("10000"),
        "gross_exposure": _usdt("6000"),
        "net_exposure": _usdt("6000"),
        "peak_equity": _usdt("12000"),
    }
    return PortfolioSnapshot(**{**base, **overrides})  # type: ignore[arg-type]


class TestCashAccounting:
    def test_reserved_cash_cannot_exceed_cash(self) -> None:
        """Two decisions must not be able to spend the same funds."""
        with pytest.raises(ValidationError, match="reserved cash exceeds total cash"):
            _portfolio(reserved_cash=_usdt("5000"))

    def test_available_cash_excludes_reservations(self) -> None:
        assert _portfolio().available_cash == _usdt("3500")

    def test_every_money_field_uses_the_base_currency(self) -> None:
        with pytest.raises(ValidationError, match="must be denominated in USDT"):
            _portfolio(cash=Money(amount="4000", currency="USD"))


class TestExposure:
    def test_exposure_percentage_is_exact(self) -> None:
        assert _portfolio().exposure_pct_for(BTC) == Decimal("60")

    def test_unheld_instruments_have_zero_exposure(self) -> None:
        assert _portfolio().exposure_pct_for(ETH) == Decimal(0)

    def test_unmarked_positions_report_unknown_exposure_not_zero(self) -> None:
        """An unpriced position is unknown risk. Risk must fail closed, not treat it as flat."""
        portfolio = _portfolio(positions=[_position(mark_price=None)])
        assert portfolio.exposure_pct_for(BTC) is None
        assert portfolio.positions[0].market_value is None

    def test_gross_exposure_is_absolute(self) -> None:
        with pytest.raises(ValidationError, match="must not be negative"):
            _portfolio(gross_exposure=_usdt("-1"))

    def test_duplicate_positions_are_refused(self) -> None:
        with pytest.raises(ValidationError, match="duplicate instrument"):
            _portfolio(positions=[_position(), _position()])


class TestDrawdown:
    def test_drawdown_is_measured_from_peak_equity(self) -> None:
        assert _portfolio().drawdown_pct == Decimal("16.66666666666666666666666667")

    def test_peak_equity_cannot_be_below_current_equity(self) -> None:
        with pytest.raises(ValidationError, match="peak equity must be at least"):
            _portfolio(peak_equity=_usdt("5000"))

    def test_zero_peak_equity_does_not_divide_by_zero(self) -> None:
        portfolio = _portfolio(
            cash=_usdt("0"),
            reserved_cash=_usdt("0"),
            positions=[],
            equity=_usdt("0"),
            gross_exposure=_usdt("0"),
            net_exposure=_usdt("0"),
            peak_equity=_usdt("0"),
            unrealized_pnl=_usdt("0"),
        )
        assert portfolio.drawdown_pct == Decimal(0)


class TestReconciliation:
    def test_unreconciled_state_is_explicit(self) -> None:
        """Risk must be able to see that the platform does not trust this view."""
        assert _portfolio(is_reconciled=False).is_reconciled is False
