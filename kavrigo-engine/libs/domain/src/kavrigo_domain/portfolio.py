"""Portfolio state (``MASTER_BUILD_SPEC.md`` §50).

The canonical ledger is decimal throughout, and authoritative account state is never derived
from a UI calculation. ``reserved_cash`` is tracked separately from ``cash`` because an open
buy order has already committed funds that a second decision must not spend twice.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Self

from pydantic import Field, model_validator

from kavrigo_domain.agent import TradingMode
from kavrigo_domain.base import DomainModel, UtcDatetime
from kavrigo_domain.identifiers import InstrumentId, WorkspaceId
from kavrigo_domain.money import Money, Price, Quantity

__all__ = ["PortfolioSnapshot", "Position"]


class Position(DomainModel):
    """A held position. Negative quantity represents short exposure (not executable in V1)."""

    instrument_id: InstrumentId
    quantity: Quantity
    average_entry_price: Price | None = None
    mark_price: Price | None = None
    realized_pnl: Money
    unrealized_pnl: Money
    opened_at: UtcDatetime | None = None
    network: Annotated[str | None, Field(default=None, max_length=32)] = None
    """Network or sector tag used for concentration limits (``MASTER_BUILD_SPEC.md`` §11.2)."""

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.quantity.asset != self.instrument_id.base:
            raise ValueError("position quantity asset must be the instrument's base asset")
        if self.realized_pnl.currency != self.unrealized_pnl.currency:
            raise ValueError("realized and unrealized P&L must share a currency")
        return self

    @property
    def market_value(self) -> Money | None:
        """Signed market value in the quote currency, or ``None`` without a mark price.

        Returning ``None`` rather than zero is deliberate: an unmarked position is unknown
        exposure, and the risk engine must reject rather than treat it as flat.
        """
        if self.mark_price is None:
            return None
        return self.mark_price.notional_for(self.quantity)


class PortfolioSnapshot(DomainModel):
    """Point-in-time portfolio state used by the portfolio and risk layers."""

    workspace_id: WorkspaceId
    mode: TradingMode
    as_of: UtcDatetime
    base_currency: Annotated[str, Field(pattern=r"^[A-Z0-9]{2,16}$")]
    cash: Money
    reserved_cash: Money
    positions: Annotated[list[Position], Field(max_length=512)] = []
    realized_pnl_today: Money
    unrealized_pnl: Money
    equity: Money
    gross_exposure: Money
    net_exposure: Money
    peak_equity: Money
    open_order_count: Annotated[int, Field(ge=0)] = 0
    is_reconciled: bool = True
    """False means the platform does not currently trust this view. Risk must fail closed
    (``MASTER_BUILD_SPEC.md`` §11.1)."""

    reconciled_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        monies = {
            "cash": self.cash,
            "reserved_cash": self.reserved_cash,
            "realized_pnl_today": self.realized_pnl_today,
            "unrealized_pnl": self.unrealized_pnl,
            "equity": self.equity,
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "peak_equity": self.peak_equity,
        }
        for name, money in monies.items():
            if money.currency != self.base_currency:
                raise ValueError(f"{name} must be denominated in {self.base_currency}")
        if self.reserved_cash.is_negative:
            raise ValueError("reserved cash must not be negative")
        if self.reserved_cash.amount > self.cash.amount:
            raise ValueError("reserved cash exceeds total cash")
        if self.gross_exposure.is_negative:
            raise ValueError("gross exposure is an absolute measure and must not be negative")
        if self.peak_equity.amount < self.equity.amount:
            raise ValueError("peak equity must be at least current equity")
        duplicates = [i.instrument_id.value for i in self.positions]
        if len(duplicates) != len(set(duplicates)):
            raise ValueError("duplicate instrument in portfolio positions")
        return self

    @property
    def available_cash(self) -> Money:
        """Cash not already committed to open orders."""
        return self.cash - self.reserved_cash

    @property
    def drawdown_pct(self) -> Decimal:
        """Drawdown from peak equity, as a percentage.

        Returns zero when peak equity is zero: an account that has never held value cannot be in
        drawdown, and dividing by zero here would take out the risk engine.
        """
        if self.peak_equity.is_zero:
            return Decimal(0)
        drop = self.peak_equity.amount - self.equity.amount
        return (drop / self.peak_equity.amount) * Decimal(100)

    def exposure_pct_for(self, instrument_id: InstrumentId) -> Decimal | None:
        """Absolute exposure to one instrument as a percentage of equity.

        ``None`` when the position cannot be valued — unknown exposure, not zero exposure.
        """
        if self.equity.is_zero:
            return Decimal(0)
        for position in self.positions:
            if position.instrument_id.value == instrument_id.value:
                value = position.market_value
                if value is None:
                    return None
                return (abs(value.amount) / self.equity.amount) * Decimal(100)
        return Decimal(0)
