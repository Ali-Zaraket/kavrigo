"""Internal synthetic execution and replay contracts; no provider wire schema."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from kavrigo_domain import DomainModel, InstrumentId, Money, Order, PortfolioSnapshot
from kavrigo_domain.base import UtcDatetime
from kavrigo_domain.identifiers import InstrumentClass
from kavrigo_domain.money import ExactDecimal
from kavrigo_risk import PaperRiskPermit
from kavrigo_risk.contracts import Digest, Duration, Name
from kavrigo_risk.fixed import product, units

Positive = Annotated[ExactDecimal, Field(gt=0)]


class PaperInstrument(DomainModel):
    instrument_id: InstrumentId
    quantity_step: Positive
    price_tick: Positive
    minimum_notional_usd: Positive
    network: Name

    @model_validator(mode="after")
    def _precision(self) -> Self:
        if (
            self.instrument_id.quote != "USD"
            or self.instrument_id.instrument_class is not InstrumentClass.SPOT
        ):
            raise ValueError("paper simulator supports USD spot only")
        product(units(self.quantity_step), units(self.price_tick))
        units(self.minimum_notional_usd)
        return self


class PaperConfig(DomainModel):
    version: Name
    latency_ms: Annotated[int, Field(strict=True, ge=0, le=60_000)]
    max_market_age_ms: Duration
    instruments: Annotated[tuple[PaperInstrument, ...], Field(min_length=1, max_length=512)]

    @model_validator(mode="after")
    def _unique(self) -> Self:
        keys = [item.instrument_id.value for item in self.instruments]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate instrument configuration")
        return self


class PaperLevel(DomainModel):
    price: Positive
    quantity: Positive


class PaperBook(DomainModel):
    """Synthetic full depth observed at received_at; resync is an explicit feed assertion."""

    instrument_id: InstrumentId
    sequence: Annotated[int, Field(strict=True, ge=1)]
    event_time: UtcDatetime
    received_at: UtcDatetime
    bids: Annotated[tuple[PaperLevel, ...], Field(min_length=1, max_length=32)]
    asks: Annotated[tuple[PaperLevel, ...], Field(min_length=1, max_length=32)]
    resync: bool = False

    @model_validator(mode="after")
    def _book(self) -> Self:
        if self.event_time > self.received_at:
            raise ValueError("market event cannot arrive before event time")
        bids, asks = [x.price for x in self.bids], [x.price for x in self.asks]
        if bids != sorted(set(bids), reverse=True) or asks != sorted(set(asks)):
            raise ValueError("book levels must be distinct and ordered")
        if bids[0] >= asks[0]:
            raise ValueError("crossed or locked book")
        return self


class PaperCommand(DomainModel):
    kind: Literal["submit", "market", "cancel"]
    at: UtcDatetime
    permit: PaperRiskPermit | None = None
    book: PaperBook | None = None
    client_order_id: str | None = None
    blocked_intents: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _shape(self) -> Self:
        expected = {
            "submit": (True, False, False),
            "market": (False, True, False),
            "cancel": (False, False, True),
        }[self.kind]
        if (
            self.permit is not None,
            self.book is not None,
            self.client_order_id is not None,
        ) != expected:
            raise ValueError("invalid paper command payload")
        if self.kind != "market" and self.blocked_intents:
            raise ValueError("only market commands contain risk recheck results")
        return self


class PaperJournalEntry(DomainModel):
    sequence: Annotated[int, Field(strict=True, ge=1)]
    previous_hash: Digest
    command: PaperCommand
    state_hash: Digest
    entry_hash: Digest


class PaperAccountState(DomainModel):
    account_id: Name
    portfolio: PortfolioSnapshot
    orders: tuple[Order, ...]
    cost_basis: dict[str, Money]
    mark_times: dict[str, UtcDatetime]
    fees_paid: Money
    batch_sealed: bool


class PaperReplay(DomainModel):
    format_version: Literal["paper-v1"] = "paper-v1"
    account_id: Name
    initial_portfolio: PortfolioSnapshot
    config: PaperConfig
    entries: Annotated[tuple[PaperJournalEntry, ...], Field(max_length=1000)]


class PaperReconciliation(DomainModel):
    sequence: Annotated[int, Field(strict=True, ge=0)]
    discovered_fill_ids: tuple[str, ...]
    state_hash: Digest
    reconciled_at: UtcDatetime
