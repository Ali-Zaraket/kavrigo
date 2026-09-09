"""Deterministic replay kernel. Integer balances are authoritative; averages are projections."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, localcontext

from kavrigo_domain import (
    Fill,
    LiquidityFlag,
    Money,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    PortfolioSnapshot,
    Position,
    Price,
    Quantity,
    TimeInForce,
    TradingMode,
    content_hash,
)
from kavrigo_paper.contracts import PaperAccountState, PaperBook, PaperCommand, PaperConfig
from kavrigo_risk import PaperRiskPermit
from kavrigo_risk.evaluator import account_state, age_ms
from kavrigo_risk.fixed import BPS_DENOMINATOR, SCALE, ceil_div, decimal, product, units

# Canonical Order validates its fill sum with Decimal. Fix that validation context; accounting
# itself never depends on Decimal arithmetic. Bounds are much smaller than this precision.
VALIDATION_CONTEXT = Context(prec=80, rounding=ROUND_HALF_EVEN)


class PaperError(ValueError):
    """Closed errors contain no source, financial amount or exception payload."""


def money(value: int) -> Money:
    return Money(amount=decimal(value), currency="USD")


def identity(prefix: str, value: object) -> str:
    return prefix + "_" + content_hash(value).removeprefix("sha256:")[:32]


def average(gross: int, quantity: int) -> int:
    quotient, remainder = divmod(gross * SCALE, quantity)
    return quotient + int(remainder * 2 > quantity or (remainder * 2 == quantity and quotient % 2))


@dataclass
class Holding:
    quantity: int
    basis: int
    mark: int
    realized: int
    opened_at: datetime | None


@dataclass
class WorkingOrder:
    permit: PaperRiskPermit
    order: Order
    target: int
    gross: int = 0
    debit: int = 0


class Ledger:
    def __init__(self, account_id: str, initial: PortfolioSnapshot, config: PaperConfig) -> None:
        if (
            initial.mode not in (TradingMode.PAPER, TradingMode.BACKTEST)
            or not initial.is_reconciled
        ):
            raise PaperError("invalid_initial_account")
        self.account_id, self.initial, self.config = account_id, initial, config
        self.instruments = {item.instrument_id.value: item for item in config.instruments}
        account_state(initial, {key: item.network for key, item in self.instruments.items()}, ())
        if initial.reconciled_at is None or initial.reconciled_at > initial.as_of:
            raise PaperError("invalid_initial_reconciliation")
        self.cash, self.peak = units(initial.cash.amount), units(initial.peak_equity.amount)
        self.realized: dict[date, int] = {
            initial.as_of.date(): units(initial.realized_pnl_today.amount)
        }
        self.fees = 0
        self.holdings: dict[str, Holding] = {}
        self.mark_times: dict[str, datetime] = {}
        unrealized = 0
        for position in initial.positions:
            key = position.instrument_id.value
            if position.average_entry_price is None or position.mark_price is None:
                raise PaperError("unknown_initial_cost_basis")
            expected = (position.instrument_id.base, "USD")
            if (position.average_entry_price.base, position.average_entry_price.quote) != expected:
                raise PaperError("invalid_initial_cost_basis")
            quantity = units(position.quantity.value)
            basis = product(quantity, units(position.average_entry_price.value))
            pnl = product(quantity, units(position.mark_price.value)) - basis
            if (
                position.realized_pnl.currency != "USD"
                or position.unrealized_pnl.currency != "USD"
                or units(position.unrealized_pnl.amount) != pnl
                or position.network not in (None, self.instruments[key].network)
            ):
                raise PaperError("inconsistent_initial_position")
            unrealized += pnl
            self.holdings[key] = Holding(
                quantity,
                basis,
                units(position.mark_price.value),
                units(position.realized_pnl.amount),
                position.opened_at,
            )
            self.mark_times[key] = initial.as_of
        if units(initial.unrealized_pnl.amount) != unrealized:
            raise PaperError("inconsistent_initial_unrealized_pnl")
        self.orders: dict[str, WorkingOrder] = {}
        self.books: dict[str, PaperBook] = {}
        self.healthy: dict[str, bool] = {}
        self.as_of = initial.as_of
        self.sealed = False

    def price(self, key: str, value: int) -> Price:
        return Price(
            value=decimal(value), base=self.instruments[key].instrument_id.base, quote="USD"
        )

    def quantity(self, key: str, value: int) -> Quantity:
        return Quantity(value=decimal(value), asset=self.instruments[key].instrument_id.base)

    def reserved_cash(self) -> int:
        return sum(
            units(item.permit.record.max_cash_debit.amount) - item.debit
            for item in self.orders.values()
            if item.order.status.is_open
        )

    def snapshot(self) -> PaperAccountState:
        with localcontext(VALIDATION_CONTEXT):
            return self._snapshot()

    def _snapshot(self) -> PaperAccountState:
        positions: list[Position] = []
        exposure = unrealized = 0
        for key, holding in sorted(self.holdings.items()):
            if not holding.quantity:
                continue
            value = product(holding.quantity, holding.mark)
            exposure += value
            unrealized += value - holding.basis
            positions.append(
                Position(
                    instrument_id=self.instruments[key].instrument_id,
                    quantity=self.quantity(key, holding.quantity),
                    average_entry_price=self.price(key, average(holding.basis, holding.quantity)),
                    mark_price=self.price(key, holding.mark),
                    realized_pnl=money(holding.realized),
                    unrealized_pnl=money(value - holding.basis),
                    opened_at=holding.opened_at,
                    network=self.instruments[key].network,
                )
            )
        equity = self.cash + exposure
        portfolio = PortfolioSnapshot(
            workspace_id=self.initial.workspace_id,
            mode=self.initial.mode,
            as_of=self.as_of,
            base_currency="USD",
            cash=money(self.cash),
            reserved_cash=money(self.reserved_cash()),
            positions=positions,
            realized_pnl_today=money(self.realized.get(self.as_of.date(), 0)),
            unrealized_pnl=money(unrealized),
            equity=money(equity),
            gross_exposure=money(exposure),
            net_exposure=money(exposure),
            peak_equity=money(max(equity, self.peak)),
            open_order_count=sum(item.order.status.is_open for item in self.orders.values()),
            is_reconciled=all(self.healthy.values())
            and all(
                age_ms(self.as_of, self.mark_times[key]) <= self.config.max_market_age_ms
                for key, holding in self.holdings.items()
                if holding.quantity
            ),
            reconciled_at=self.as_of,
        )
        return PaperAccountState(
            account_id=self.account_id,
            portfolio=portfolio,
            orders=tuple(item.order for item in self.orders.values()),
            cost_basis={key: money(item.basis) for key, item in sorted(self.holdings.items())},
            mark_times=dict(sorted(self.mark_times.items())),
            fees_paid=money(self.fees),
            batch_sealed=self.sealed,
        )

    def apply(self, command: PaperCommand) -> "Ledger":
        if command.at < self.as_of:
            raise PaperError("out_of_order_command")
        next_state = deepcopy(self)
        with localcontext(VALIDATION_CONTEXT):
            if command.kind == "submit":
                assert command.permit is not None
                next_state._submit(command.permit, command.at)
            elif command.kind == "market":
                assert command.book is not None
                next_state._market(command.book, command.at, set(command.blocked_intents))
            else:
                assert command.client_order_id is not None
                item = next_state.orders.get(command.client_order_id)
                if item is None:
                    raise PaperError("unknown_order")
                if item.order.status.is_open:
                    next_state._status(
                        item, OrderStatus.CANCELLED, command.at, "cancelled_by_coordinator"
                    )
            next_state.as_of = command.at
            snapshot = next_state.snapshot()
            next_state.peak = units(snapshot.portfolio.peak_equity.amount)
        return next_state

    def _status(
        self, item: WorkingOrder, status: OrderStatus, at: datetime, reason: str | None = None
    ) -> None:
        item.order = Order.model_validate(
            {
                **item.order.model_dump(mode="python"),
                "status": status,
                "last_updated_at": at,
                "reject_reason": reason,
                "reconciled_at": at,
            }
        )

    def _submit(self, permit: PaperRiskPermit, at: datetime) -> None:
        approval, record = permit.approval, permit.record
        key = approval.instrument_id.value
        if self.sealed:
            raise PaperError("batch_sealed")
        if (
            key not in self.instruments
            or permit.account_id != self.account_id
            or record.account_id != self.account_id
            or approval.workspace_id != self.initial.workspace_id
            or approval.mode != self.initial.mode
            or record.portfolio_hash != content_hash(self.initial)
            or record.evaluation.workspace_id != self.initial.workspace_id
            or record.evaluation.order_intent_id != approval.order_intent_id
            or record.evaluation.risk_evaluation_id != approval.risk_evaluation_id
            or not record.evaluation.is_approved
            or record.evaluation.approved_notional != approval.approved_notional
            or approval.approved_at > at
            or at >= min(approval.expires_at, record.expires_at)
            or approval.order_type is not OrderType.MARKET
            or approval.time_in_force is not TimeInForce.IOC
            or approval.limit_price is not None
            or record.max_quantity.asset != approval.instrument_id.base
            or record.max_cash_debit.currency != "USD"
            or approval.approved_notional.currency != "USD"
            or approval.client_order_id in self.orders
            or any(
                x.order.order_intent_id == approval.order_intent_id for x in self.orders.values()
            )
        ):
            raise PaperError("invalid_paper_issuance")
        lot = units(self.instruments[key].quantity_step)
        target = units(record.max_quantity.value) // lot * lot
        debit = units(record.max_cash_debit.amount)
        if debit < 0 or debit > self.cash - self.reserved_cash():
            raise PaperError("insufficient_unreserved_cash")
        if approval.side is OrderSide.SELL:
            reserved = sum(
                other.target
                for other in self.orders.values()
                if other.order.status.is_open
                and other.order.side is OrderSide.SELL
                and other.order.instrument_id == approval.instrument_id
            )
            held = self.holdings.get(key)
            if held is None or target > held.quantity - reserved:
                raise PaperError("insufficient_unreserved_quantity")
        order = Order(
            order_id=identity(
                "ord",
                {
                    "account": self.account_id,
                    "workspace": self.initial.workspace_id,
                    "client": approval.client_order_id,
                },
            ),
            client_order_id=approval.client_order_id,
            order_intent_id=approval.order_intent_id,
            workspace_id=approval.workspace_id,
            instrument_id=approval.instrument_id,
            mode=approval.mode,
            side=approval.side,
            order_type=approval.order_type,
            status=OrderStatus.SUBMITTED,
            requested_notional=approval.approved_notional,
            filled_quantity=self.quantity(key, 0),
            fees_paid=money(0),
            submitted_at=at,
            last_updated_at=at,
            reconciled_at=at,
        )
        item = WorkingOrder(permit, order, target)
        if target <= 0 or units(approval.approved_notional.amount) < units(
            self.instruments[key].minimum_notional_usd
        ):
            self._status(item, OrderStatus.REJECTED, at, "below_simulator_minimum")
        self.orders[order.client_order_id] = item

    def _market(self, book: PaperBook, at: datetime, blocked: set[str]) -> None:
        key = book.instrument_id.value
        if key not in self.instruments or book.received_at > at:
            raise PaperError("invalid_market_scope_or_time")
        previous = self.books.get(key)
        if previous and (
            book.sequence <= previous.sequence
            or book.received_at < previous.received_at
            or book.event_time < previous.event_time
        ):
            raise PaperError("out_of_order_market")
        config = self.instruments[key]
        lot, tick = units(config.quantity_step), units(config.price_tick)
        for level in (*book.bids, *book.asks):
            if units(level.price) % tick or units(level.quantity) % lot:
                raise PaperError("invalid_market_increment")
        expected = previous.sequence + 1 if previous else 1
        healthy = (
            (book.resync or (book.sequence == expected and self.healthy.get(key, True)))
            and age_ms(at, book.event_time) <= self.config.max_market_age_ms
            and age_ms(at, book.received_at) <= self.config.max_market_age_ms
        )
        self.books[key], self.healthy[key] = book, healthy
        if healthy and key in self.holdings:
            self.holdings[key].mark = units(book.bids[0].price)
            self.mark_times[key] = book.event_time
        depth = {
            OrderSide.BUY: [units(x.quantity) for x in book.asks],
            OrderSide.SELL: [units(x.quantity) for x in book.bids],
        }
        for item in self.orders.values():
            order, approval = item.order, item.permit.approval
            if not order.status.is_open or order.instrument_id != book.instrument_id:
                continue
            assert order.submitted_at is not None
            if at >= approval.expires_at:
                self._status(item, OrderStatus.EXPIRED, at, "approval_expired")
                continue
            ready_at = order.submitted_at + timedelta(milliseconds=self.config.latency_ms)
            if book.event_time < ready_at or book.received_at < ready_at:
                continue
            self.sealed = True
            if approval.order_intent_id in blocked:
                self._status(item, OrderStatus.CANCELLED, at, "risk_recheck_rejected")
                continue
            if not healthy or age_ms(at, book.event_time) > item.permit.execution.max_market_age_ms:
                self._status(item, OrderStatus.CANCELLED, at, "market_unhealthy")
                continue
            self._status(item, OrderStatus.ACCEPTED, at)
            levels = book.asks if order.side is OrderSide.BUY else book.bids
            for index, level in enumerate(levels):
                self._fill_level(item, book, index, units(level.price), depth[order.side], at)
                if units(item.order.filled_quantity.value) == item.target:
                    break
            if units(item.order.filled_quantity.value) == item.target:
                self._status(item, OrderStatus.FILLED, at)
            else:
                self._status(item, OrderStatus.CANCELLED, at, "ioc_remainder_cancelled")

    def _fill_level(
        self,
        item: WorkingOrder,
        book: PaperBook,
        index: int,
        raw_price: int,
        depth: list[int],
        at: datetime,
    ) -> None:
        key, side = book.instrument_id.value, item.order.side
        settings = self.instruments[key]
        lot, tick = units(settings.quantity_step), units(settings.price_tick)
        slip, fee_bps = (
            units(item.permit.execution.slippage_bps),
            units(item.permit.execution.fee_bps),
        )
        numerator = raw_price * (
            BPS_DENOMINATOR + slip if side is OrderSide.BUY else BPS_DENOMINATOR - slip
        )
        price = (
            ceil_div(numerator, BPS_DENOMINATOR * tick)
            if side is OrderSide.BUY
            else numerator // (BPS_DENOMINATOR * tick)
        ) * tick
        if price <= 0:
            return
        remaining = item.target - units(item.order.filled_quantity.value)
        maximum = min(remaining, depth[index]) // lot
        budget = units(item.permit.approval.approved_notional.amount) - item.gross
        cash_limit = units(item.permit.record.max_cash_debit.amount) - item.debit

        def allowed(lots: int) -> bool:
            gross = product(lots * lot, price)
            fee = ceil_div(gross * fee_bps, BPS_DENOMINATOR)
            return gross <= budget and ((gross if side is OrderSide.BUY else 0) + fee) <= cash_limit

        low, high = 0, maximum
        while low < high:
            middle = (low + high + 1) // 2
            if allowed(middle):
                low = middle
            else:
                high = middle - 1
        quantity = low * lot
        if not quantity:
            return
        gross = product(quantity, price)
        fee = ceil_div(gross * fee_bps, BPS_DENOMINATOR)
        debit = (gross if side is OrderSide.BUY else 0) + fee
        holding = self.holdings.setdefault(key, Holding(0, 0, units(book.bids[0].price), 0, at))
        self.mark_times[key] = book.event_time
        if side is OrderSide.BUY:
            if self.cash < debit:
                raise PaperError("cash_invariant")
            self.cash -= debit
            holding.quantity += quantity
            holding.basis += gross
            realized = -fee
        else:
            if holding.quantity < quantity or self.cash < fee:
                raise PaperError("position_invariant")
            basis = holding.basis * quantity // holding.quantity
            holding.quantity -= quantity
            holding.basis -= basis
            self.cash += gross - fee
            realized = gross - basis - fee
        holding.realized += realized
        self.realized[at.date()] = self.realized.get(at.date(), 0) + realized
        self.fees += fee
        item.gross += gross
        item.debit += debit
        depth[index] -= quantity
        fill = Fill(
            fill_id=identity(
                "fill", {"order": item.order.order_id, "book": content_hash(book), "level": index}
            ),
            order_id=item.order.order_id,
            workspace_id=self.initial.workspace_id,
            instrument_id=book.instrument_id,
            side=side,
            quantity=self.quantity(key, quantity),
            price=self.price(key, price),
            fee=money(fee),
            liquidity=LiquidityFlag.TAKER,
            venue_fill_id=f"paper-{book.sequence}-{index}",
            venue_timestamp=book.event_time,
            recorded_at=at,
            sequence=book.sequence,
        )
        filled = units(item.order.filled_quantity.value) + quantity
        item.order = Order.model_validate(
            {
                **item.order.model_dump(mode="python"),
                "fills": [*item.order.fills, fill],
                "filled_quantity": self.quantity(key, filled),
                "fees_paid": money(units(item.order.fees_paid.amount) + fee),
                "average_fill_price": self.price(key, average(item.gross, filled)),
                "status": OrderStatus.PARTIALLY_FILLED,
                "last_updated_at": at,
            }
        )
