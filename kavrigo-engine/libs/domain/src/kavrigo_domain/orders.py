"""Order intents, approvals, orders and fills (``MASTER_BUILD_SPEC.md`` §15).

The chain is deliberately one-directional:

```text
AgentDecision → OrderIntent → RiskEvaluation → ApprovedOrderIntent → execution adapter → Order → Fill
```

An ``OrderIntent`` is a *request*. Only the deterministic risk engine can turn one into an
``ApprovedOrderIntent``, and only an ``ApprovedOrderIntent`` — carrying a risk evaluation id, a
deterministic client order id and a fencing token — is accepted by an execution adapter.

Two failure modes get explicit types here because they are the ones that duplicate real money:

* **Duplicate submission.** ``client_order_id`` is deterministic and idempotent; retrying a
  command must never create a second order (``AGENTS.md`` domain rule 7).
* **Split brain.** ``fencing_token`` increments per execution lease. A stale token is rejected,
  so two executors cannot both write for one account (``AGENTS.md`` domain rule 8, §15.5).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, model_validator

from kavrigo_domain.agent import TradingMode
from kavrigo_domain.base import DomainModel, UtcDatetime
from kavrigo_domain.identifiers import (
    AgentVersionId,
    DecisionId,
    FillId,
    InstrumentClass,
    InstrumentId,
    OrderId,
    OrderIntentId,
    WorkspaceId,
)
from kavrigo_domain.money import ExactDecimal, Money, Price, Quantity

__all__ = [
    "ApprovedOrderIntent",
    "Fill",
    "LiquidityFlag",
    "Order",
    "OrderIntent",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "TimeInForce",
]


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(StrEnum):
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"
    DAY = "day"


class OrderStatus(StrEnum):
    """Canonical order state machine.

    Venue-specific statuses are mapped onto this set by each adapter, so that reconciliation and
    the UI reason about one vocabulary. ``UNKNOWN`` exists because a timeout after submission is
    a real state: the platform must be able to say "we do not know" and fail closed rather than
    assume the order did not arrive.
    """

    PENDING_SUBMIT = "pending_submit"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    UNKNOWN = "unknown"

    @property
    def is_terminal(self) -> bool:
        return self in {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }

    @property
    def is_open(self) -> bool:
        return self in {
            OrderStatus.PENDING_SUBMIT,
            OrderStatus.SUBMITTED,
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
        }


class LiquidityFlag(StrEnum):
    MAKER = "maker"
    TAKER = "taker"
    UNKNOWN = "unknown"


class OrderIntent(DomainModel):
    """A proposed order awaiting deterministic risk evaluation.

    This type deliberately has no venue credentials, no venue order id, and no method that
    reaches a venue. It is inert until risk approves it.
    """

    order_intent_id: OrderIntentId
    decision_id: DecisionId
    workspace_id: WorkspaceId
    agent_version_id: AgentVersionId
    instrument_id: InstrumentId
    mode: TradingMode
    side: OrderSide
    order_type: OrderType
    notional: Money
    limit_price: Price | None = None
    time_in_force: TimeInForce = TimeInForce.IOC
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128)]
    """Stable across retries of the same logical intent (``AGENTS.md`` domain rule 7)."""

    created_at: UtcDatetime
    expires_at: UtcDatetime
    """Intents expire. A stale intent executed minutes later is a different trade than the one
    the evidence supported."""

    estimated_cost_bps: ExactDecimal | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.mode is TradingMode.LIVE:
            raise ValueError(
                "live order intents are not constructible while live trading is gated "
                "(ADR 0001); use TradingMode.PAPER"
            )
        if self.instrument_id.instrument_class is not InstrumentClass.SPOT:
            raise ValueError("V1 executes spot instruments only (ADR 0002)")
        if self.notional.is_negative or self.notional.is_zero:
            raise ValueError("intent notional must be positive; direction is carried by `side`")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("a limit order requires a limit price")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("a market order must not carry a limit price")
        if self.limit_price is not None:
            expected = (self.instrument_id.base, self.instrument_id.quote)
            if (self.limit_price.base, self.limit_price.quote) != expected:
                raise ValueError("limit price assets do not match the instrument")
        if self.notional.currency != self.instrument_id.quote:
            raise ValueError(
                f"notional currency {self.notional.currency} must be the instrument's quote "
                f"currency {self.instrument_id.quote}"
            )
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self

    def is_expired_at(self, now: UtcDatetime) -> bool:
        return now >= self.expires_at


class ApprovedOrderIntent(DomainModel):
    """A risk-approved intent — the only thing an execution adapter accepts.

    Constructing one validates its fields, not the authority of its issuer. Consumers must
    authenticate the risk service and resolve the recorded evaluation before accepting it.
    The local risk session issues this within a paper permit carrying additional quantity and
    cash ceilings. A model has no tool for issuing an approval.
    """

    order_intent_id: OrderIntentId
    risk_evaluation_id: Annotated[str, Field(pattern=r"^re_[0-9a-f]{32}$")]
    workspace_id: WorkspaceId
    instrument_id: InstrumentId
    mode: TradingMode
    side: OrderSide
    order_type: OrderType
    approved_notional: Money
    limit_price: Price | None = None
    time_in_force: TimeInForce
    client_order_id: Annotated[str, Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
    """Deterministic and venue-safe. The dedupe key for at-least-once delivery (§15.4)."""

    fencing_token: Annotated[int, Field(ge=1)]
    """Increments on execution-lease acquisition. Adapters reject stale tokens (§15.5)."""

    approved_at: UtcDatetime
    expires_at: UtcDatetime

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.mode is TradingMode.LIVE:
            raise ValueError("live execution is gated (ADR 0001)")
        if self.approved_notional.is_zero or self.approved_notional.is_negative:
            raise ValueError("approved notional must be positive")
        if self.expires_at <= self.approved_at:
            raise ValueError("expires_at must be after approved_at")
        return self


class Fill(DomainModel):
    """One execution against an order. Immutable and idempotent by ``fill_id``."""

    fill_id: FillId
    order_id: OrderId
    workspace_id: WorkspaceId
    instrument_id: InstrumentId
    side: OrderSide
    quantity: Quantity
    price: Price
    fee: Money
    liquidity: LiquidityFlag = LiquidityFlag.UNKNOWN
    venue_fill_id: Annotated[str | None, Field(default=None, max_length=128)] = None
    venue_timestamp: UtcDatetime
    recorded_at: UtcDatetime
    sequence: Annotated[int | None, Field(default=None, ge=0)] = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.quantity.value <= 0:
            raise ValueError("fill quantity must be positive; direction is carried by `side`")
        if self.quantity.asset != self.instrument_id.base:
            raise ValueError("fill quantity asset must be the instrument's base asset")
        if (self.price.base, self.price.quote) != (
            self.instrument_id.base,
            self.instrument_id.quote,
        ):
            raise ValueError("fill price assets do not match the instrument")
        if self.fee.is_negative:
            raise ValueError("fee must not be negative; rebates are modelled explicitly")
        return self

    @property
    def notional(self) -> Money:
        """Gross value of the fill in the quote currency, excluding fees."""
        return self.price.notional_for(self.quantity)


class Order(DomainModel):
    """Canonical order state, owned by the platform and reconciled against the venue.

    The venue is the authority on what happened; this record is the platform's reconciled view
    of it (``MASTER_BUILD_SPEC.md`` §15.4). ``OrderStatus.UNKNOWN`` is retained rather than
    guessed until reconciliation resolves it.
    """

    order_id: OrderId
    client_order_id: Annotated[str, Field(min_length=8, max_length=64)]
    order_intent_id: OrderIntentId
    workspace_id: WorkspaceId
    instrument_id: InstrumentId
    mode: TradingMode
    side: OrderSide
    order_type: OrderType
    status: OrderStatus
    requested_notional: Money
    filled_quantity: Quantity
    average_fill_price: Price | None = None
    fees_paid: Money
    venue_order_id: Annotated[str | None, Field(default=None, max_length=128)] = None
    fills: Annotated[list[Fill], Field(max_length=1000)] = []
    submitted_at: UtcDatetime | None = None
    last_updated_at: UtcDatetime
    reject_reason: Annotated[str | None, Field(default=None, max_length=512)] = None
    reconciled_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.mode is TradingMode.LIVE:
            raise ValueError("live orders are not constructible while live trading is gated")
        if self.filled_quantity.value < 0:
            raise ValueError("filled quantity must not be negative")
        if self.filled_quantity.asset != self.instrument_id.base:
            raise ValueError("filled quantity asset must be the instrument's base asset")
        if self.status is OrderStatus.FILLED and self.filled_quantity.is_zero:
            raise ValueError("a FILLED order must have a non-zero filled quantity")
        if self.status is OrderStatus.REJECTED and not self.filled_quantity.is_zero:
            raise ValueError("a REJECTED order cannot have fills")

        total = sum((fill.quantity.value for fill in self.fills), start=Decimal(0))
        if self.fills and total != self.filled_quantity.value:
            raise ValueError(
                f"filled quantity {self.filled_quantity.value} does not match the sum of fills "
                f"{total}; reconcile before persisting"
            )
        for fill in self.fills:
            if fill.order_id != self.order_id:
                raise ValueError("fill belongs to a different order")
        return self

    @property
    def is_open(self) -> bool:
        return self.status.is_open
