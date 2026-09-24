"""Point-in-time Kavrigo risk gating for the bounded Nautilus reference strategy."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import OrderSide as NautilusOrderSide
from nautilus_trader.model.identifiers import InstrumentId as NautilusInstrumentId
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Price as NautilusPrice
from nautilus_trader.trading.strategy import Strategy

from kavrigo_backtest import BacktestBar, BacktestRunConfig
from kavrigo_domain import (
    AgentDecision,
    BookTicker,
    DataQuality,
    EvidenceItem,
    FreshnessReport,
    MarketSnapshot,
    Money,
    OrderIntent,
    OrderSide,
    OrderType,
    PortfolioSnapshot,
    Position,
    Price,
    ProposedAction,
    Quantity,
    RiskDecision,
    TimeInForce,
    TradingMode,
    content_hash,
)
from kavrigo_domain.evidence import EvidenceKind, SourceClass
from kavrigo_risk import (
    LocalRiskSession,
    RiskControls,
    RiskMarket,
    RiskRegistration,
    RiskRequest,
)
from kavrigo_risk.fixed import BPS_DENOMINATOR, SCALE, decimal, units
from kavrigo_runtime import Allocation
from kavrigo_runtime.validation import snapshot_hash


def _artifact_id(prefix: str, *parts: object) -> str:
    return f"{prefix}_{content_hash(parts)[7:39]}"


class ReferenceRiskGate:
    """Construct real risk requests from engine-owned state before each simulated order."""

    def __init__(
        self,
        *,
        config: BacktestRunConfig,
        instrument_id: NautilusInstrumentId,
        venue: Venue,
        bars: tuple[BacktestBar, ...],
        price_precision: int,
        size_precision: int,
        price_increment: Decimal,
        size_increment: Decimal,
    ) -> None:
        replay = config.risk_replay
        if replay is None:
            raise ValueError("reference risk gate requires replay configuration")
        self.config = config
        self.replay = replay
        self.source_instrument = config.spec.universe.instruments[0]
        self.instrument_id = instrument_id
        self.venue = venue
        self.price_precision = price_precision
        self.size_precision = size_precision
        self.price_increment = price_increment
        self.size_increment = size_increment
        self.bars = {self._nanoseconds(item.ingested_at): item for item in bars}
        self.registration = RiskRegistration(
            agent_version=replay.agent_version,
            policies=replay.policies,
            execution=replay.execution,
            networks=replay.networks,
        )
        self.peak_equity = config.starting_balance.amount
        self.evaluations = 0
        self.approvals = 0
        self.reason_counts: Counter[str] = Counter()

    @staticmethod
    def _nanoseconds(value: datetime) -> int:
        return int(value.timestamp()) * 1_000_000_000 + value.microsecond * 1_000

    def observe(self, strategy: Strategy, bar: Bar) -> None:
        """Track peak marked equity on every closed bar for drawdown enforcement."""

        from nautilus_trader.model.currencies import Currency  # type: ignore[attr-defined]

        source = self.bars.get(bar.ts_init)
        if source is None:
            return
        try:
            quote = Currency.from_str(self.source_instrument.quote)
            account = strategy.portfolio.account(venue=self.venue)
            if account is None:
                return
            balance = account.balance_total(quote)
            if balance is None:
                return
            cash = balance.as_decimal()
            quantity = Decimal(strategy.portfolio.net_position(self.instrument_id))
            if quantity < 0:
                return
            self.peak_equity = max(self.peak_equity, cash + quantity * source.close)
        except Exception:
            # Observation is best-effort. Signal-time portfolio construction still fails closed.
            return

    def _portfolio(self, strategy: Strategy, source: BacktestBar) -> PortfolioSnapshot:
        from nautilus_trader.model.currencies import Currency  # type: ignore[attr-defined]

        quote = Currency.from_str(self.source_instrument.quote)
        account = strategy.portfolio.account(venue=self.venue)
        if account is None:
            raise ValueError("backtest account is unavailable")
        balance = account.balance_total(quote)
        if balance is None:
            raise ValueError("backtest quote balance is unavailable")
        cash = balance.as_decimal()
        quantity = Decimal(strategy.portfolio.net_position(self.instrument_id))
        if quantity < 0:
            raise ValueError("reference replay does not permit short positions")
        exposure = quantity * source.close
        equity = cash + exposure
        self.peak_equity = max(self.peak_equity, equity)
        realized = strategy.portfolio.realized_pnl(self.instrument_id, target_currency=quote)
        unrealized = strategy.portfolio.unrealized_pnl(
            self.instrument_id,
            price=NautilusPrice(source.close, self.price_precision),
            target_currency=quote,
        )
        zero = Money.zero(self.source_instrument.quote)
        positions: list[Position] = []
        if quantity > 0:
            positions.append(
                Position(
                    instrument_id=self.source_instrument,
                    quantity=Quantity(value=quantity, asset=self.source_instrument.base),
                    mark_price=Price(
                        value=source.close,
                        base=self.source_instrument.base,
                        quote=self.source_instrument.quote,
                    ),
                    realized_pnl=(
                        Money(amount=realized.as_decimal(), currency=self.source_instrument.quote)
                        if realized is not None
                        else zero
                    ),
                    unrealized_pnl=(
                        Money(
                            amount=unrealized.as_decimal(),
                            currency=self.source_instrument.quote,
                        )
                        if unrealized is not None
                        else zero
                    ),
                    network=self.replay.networks[self.source_instrument.value],
                )
            )
        realized_money = (
            Money(amount=realized.as_decimal(), currency=self.source_instrument.quote)
            if realized is not None
            else zero
        )
        unrealized_money = (
            Money(amount=unrealized.as_decimal(), currency=self.source_instrument.quote)
            if unrealized is not None
            else zero
        )
        return PortfolioSnapshot(
            workspace_id=self.config.workspace_id,
            mode=TradingMode.BACKTEST,
            as_of=source.ingested_at,
            base_currency=self.source_instrument.quote,
            cash=Money(amount=cash, currency=self.source_instrument.quote),
            reserved_cash=zero,
            positions=positions,
            realized_pnl_today=realized_money,
            unrealized_pnl=unrealized_money,
            equity=Money(amount=equity, currency=self.source_instrument.quote),
            gross_exposure=Money(amount=exposure, currency=self.source_instrument.quote),
            net_exposure=Money(amount=exposure, currency=self.source_instrument.quote),
            peak_equity=Money(amount=self.peak_equity, currency=self.source_instrument.quote),
            open_order_count=strategy.cache.orders_open_count(
                venue=self.venue, instrument_id=self.instrument_id
            ),
            reconciled_at=source.ingested_at,
        )

    def _evidence(self, source: BacktestBar, action: ProposedAction) -> tuple[EvidenceItem, ...]:
        requirements = self.config.spec.evidence
        count = max(
            requirements.min_evidence_items, 2 if requirements.require_contradicting_evidence else 1
        )
        items: list[EvidenceItem] = []
        for index in range(count):
            contradictory = requirements.require_contradicting_evidence and index == count - 1
            relation = "contradicts" if contradictory else "supports"
            summary = (
                f"Deterministic EMA reference evidence {relation} the {action.value} signal "
                f"at closed price {source.close}."
            )
            items.append(
                EvidenceItem(
                    evidence_id=_artifact_id(
                        "ev", self.config.run_id, source.ingested_at, action.value, index
                    ),
                    kind=EvidenceKind.PRICE_TECHNICAL,
                    source_class=SourceClass.DERIVED_FEATURE,
                    provider="kavrigo-reference-replay",
                    summary=summary,
                    instruments=[self.source_instrument],
                    assets=[self.source_instrument.base],
                    observed_at=source.event_time,
                    ingested_at=source.ingested_at,
                    source_ref="long-only-ema-v1",
                    content_hash=content_hash(summary),
                    quality=1.0,
                    confidence=0.5,
                    is_contradictory_candidate=contradictory,
                    license_ref="self-authored-reference-risk-v1",
                )
            )
        return tuple(items)

    def _request(
        self,
        *,
        source: BacktestBar,
        action: ProposedAction,
        requested_notional: Decimal,
    ) -> RiskRequest:
        evidence = self._evidence(source, action)
        required_families = {
            family
            for policy in self.replay.policies
            for family in policy.freshness.required_families
        }
        snapshot_id = _artifact_id("snap", self.config.run_id, source.ingested_at, action.value)
        snapshot = MarketSnapshot(
            snapshot_id=snapshot_id,
            as_of=source.ingested_at,
            created_at=source.ingested_at,
            instruments=[self.source_instrument],
            evidence_refs=[item.evidence_id for item in evidence],
            quality=DataQuality(
                score=1.0,
                freshness=FreshnessReport(age_ms=dict.fromkeys(required_families, 0)),
            ),
            dataset_manifest_ref=self.config.dataset.manifest_id,
            content_hash="sha256:" + "0" * 64,
        )
        snapshot = snapshot.model_copy(update={"content_hash": snapshot_hash(snapshot)})
        decision_id = _artifact_id("dec", self.config.run_id, source.ingested_at, action.value)
        supporting = [item.evidence_id for item in evidence if not item.is_contradictory_candidate]
        contradicting = [item.evidence_id for item in evidence if item.is_contradictory_candidate]
        decision = AgentDecision.model_validate(
            {
                "decision_id": decision_id,
                "workspace_id": self.config.workspace_id,
                "agent_version_id": self.config.agent_version_id,
                "snapshot_id": snapshot.snapshot_id,
                "instrument_id": self.source_instrument,
                "decided_at": source.ingested_at,
                "market_regime": "trend_up" if action is ProposedAction.BUY else "trend_down",
                "state": "bullish" if action is ProposedAction.BUY else "bearish",
                "signals": {},
                "prediction": {
                    "expected_return_bps": (
                        self.replay.expected_edge_bps
                        if action is ProposedAction.BUY
                        else -self.replay.expected_edge_bps
                    ),
                    "confidence": 0.5,
                    "uncertainty": 0.5,
                    "horizon_minutes": self.config.spec.analysis.horizons_minutes[0],
                },
                "proposed_action": action,
                "proposed_notional": Money(
                    amount=requested_notional, currency=self.source_instrument.quote
                ),
                "rationale": "Deterministic reference signal; no model inference.",
                "evidence_refs": supporting,
                "contradicting_evidence_refs": contradicting,
                "estimated_cost_bps": self.config.costs.one_way_cost().total_bps,
            }
        )
        requested = Money(amount=requested_notional, currency=self.source_instrument.quote)
        allocation = Allocation(
            decision_id=decision.decision_id,
            instrument_id=self.source_instrument,
            requested_notional=requested,
            allocated_notional=requested,
            reason_codes=("allocated",),
        )
        half_spread = max(
            source.close * self.config.costs.slippage.spread_crossing_bps / Decimal(10_000),
            self.price_increment,
        )
        quantum = Decimal(1).scaleb(-self.price_precision)
        bid = (source.close - half_spread).quantize(quantum)
        ask = (source.close + half_spread).quantize(quantum)
        book = BookTicker(
            instrument_id=self.source_instrument,
            bid_price=Price(
                value=bid,
                base=self.source_instrument.base,
                quote=self.source_instrument.quote,
            ),
            ask_price=Price(
                value=ask,
                base=self.source_instrument.base,
                quote=self.source_instrument.quote,
            ),
            bid_size=Quantity(value=source.volume, asset=self.source_instrument.base),
            ask_size=Quantity(value=source.volume, asset=self.source_instrument.base),
            venue_time=source.event_time,
            received_at=source.ingested_at,
        )
        intent_id = _artifact_id("oi", self.config.run_id, decision_id)
        intent = OrderIntent(
            order_intent_id=intent_id,
            decision_id=decision.decision_id,
            workspace_id=self.config.workspace_id,
            agent_version_id=self.config.agent_version_id,
            instrument_id=self.source_instrument,
            mode=TradingMode.BACKTEST,
            side=OrderSide.BUY if action is ProposedAction.BUY else OrderSide.SELL,
            order_type=OrderType.MARKET,
            notional=requested,
            time_in_force=TimeInForce.IOC,
            idempotency_key="backtest-" + intent_id[3:],
            created_at=source.ingested_at,
            expires_at=source.ingested_at
            + timedelta(milliseconds=self.replay.execution.max_approval_age_ms),
            estimated_cost_bps=self.config.costs.one_way_cost().total_bps,
        )
        return RiskRequest(
            intent=intent,
            decision=decision,
            allocation=allocation,
            snapshot=snapshot,
            evidence=evidence,
            market=RiskMarket(
                book=book,
                liquidity_usd=source.close * source.volume,
                observed_at=source.ingested_at,
            ),
        )

    def approve(
        self,
        *,
        strategy: Strategy,
        bar: Bar,
        side: NautilusOrderSide,
        requested_notional: Decimal,
    ) -> Decimal | None:
        self.evaluations += 1
        source = self.bars.get(bar.ts_init)
        if source is None:
            self.reason_counts["stale_data"] += 1
            return None
        try:
            portfolio = self._portfolio(strategy, source)
            action = ProposedAction.BUY if side is NautilusOrderSide.BUY else ProposedAction.CLOSE
            if side is NautilusOrderSide.SELL:
                half_spread = max(
                    source.close * self.config.costs.slippage.spread_crossing_bps / Decimal(10_000),
                    self.price_increment,
                )
                price_quantum = Decimal(1).scaleb(-self.price_precision)
                bid = (source.close - half_spread).quantize(price_quantum)
                held = requested_notional / source.close
                held_units = units(held)
                worst_price = (
                    units(bid)
                    * (BPS_DENOMINATOR - units(self.replay.execution.slippage_bps))
                    // BPS_DENOMINATOR
                )
                max_notional = held_units * worst_price // SCALE
                increment = units(self.replay.execution.notional_increment_usd)
                requested_notional = decimal(max_notional // increment * increment)
            request = self._request(
                source=source,
                action=action,
                requested_notional=requested_notional,
            )
            validity_ms = max(
                self.replay.execution.max_snapshot_age_ms,
                self.replay.execution.max_portfolio_age_ms,
                self.replay.execution.max_reconciliation_age_ms,
                self.replay.execution.max_market_age_ms,
                self.replay.execution.max_approval_age_ms,
            )
            controls = RiskControls(
                workspace_id=self.config.workspace_id,
                account_id=self.replay.account_id,
                version=1,
                as_of=source.ingested_at,
                valid_until=source.ingested_at + timedelta(milliseconds=validity_ms + 1),
                account_known=self.replay.account_known,
                connectivity_ok=self.replay.connectivity_ok,
                event_calendar_known=self.replay.event_calendar_known,
                active_kills=self.replay.active_kills,
                blocked_agent_versions=self.replay.blocked_agent_versions,
                macro_events=self.replay.macro_events,
                fencing_token=1,
                lease_expires_at=source.ingested_at + timedelta(milliseconds=validity_ms + 1),
            )
            session = LocalRiskSession(
                environment="local",
                portfolio=portfolio,
                controls=controls,
                registrations=(self.registration,),
                clock=lambda: source.ingested_at,
                capacity=1,
            )
            record = session.evaluate(request)
            for reason in record.evaluation.reason_codes:
                self.reason_counts[reason.value] += 1
            if record.evaluation.decision is RiskDecision.REJECTED:
                return None
            permit = session.handoff(
                workspace_id=self.config.workspace_id,
                order_intent_id=request.intent.order_intent_id,
                fencing_token=1,
            )
            if permit is None:
                self.reason_counts["handoff_refused"] += 1
                return None
            quantity = permit.record.max_quantity.value
            quantity = (quantity // self.size_increment) * self.size_increment
            quantity = quantity.quantize(
                Decimal(1).scaleb(-self.size_precision), rounding=ROUND_DOWN
            )
            if quantity <= 0:
                self.reason_counts["below_minimum_order_size"] += 1
                return None
            self.approvals += 1
            return quantity
        except Exception:
            self.reason_counts["unknown_account_state"] += 1
            return None

    @property
    def rejections(self) -> int:
        return self.evaluations - self.approvals
