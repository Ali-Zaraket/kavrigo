"""NautilusTrader implementation of :class:`kavrigo_backtest.BacktestEngine`.

ADR 0012: a stable NautilusTrader release behind our own contracts, chosen for its fill,
fee and latency realism rather than for building market simulation ourselves.

The adapter is responsible for three things beyond wiring:

* **Refusing unsafe runs.** A dataset with leakage findings does not get executed. Producing a
  number from a dataset that could see the future is worse than producing none, because the
  number is quotable (``MASTER_BUILD_SPEC.md`` §12.3).
* **Preserving cost realism across the boundary.** Fees, slippage and latency are translated
  explicitly, with units converted in one named place.
* **Recording the engine's own identity.** The reproducibility bundle names the engine and its
  version, because "the same backtest" on a different simulator is not the same backtest.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import nautilus_trader
from nautilus_trader.backtest.engine import BacktestEngine as NautilusBacktestEngine
from nautilus_trader.backtest.models import MakerTakerFeeModel
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model.currencies import USDT, Currency  # type: ignore[attr-defined]
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide
from nautilus_trader.model.identifiers import InstrumentId as NautilusInstrumentId
from nautilus_trader.model.identifiers import Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Money as NautilusMoney
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy

from kavrigo_backtest import (
    BacktestResult,
    BacktestRunConfig,
    EquityPoint,
    PerformanceMetrics,
    ReproducibilityBundle,
    RunStatus,
    TradeOutcome,
    compute_metrics,
    refuse,
)
from kavrigo_domain import Money
from kavrigo_nautilus.translation import to_nautilus_fill_model, to_nautilus_latency_model

__all__ = ["ENGINE_NAME", "NautilusBacktestAdapter"]

ENGINE_NAME = "nautilus_trader"


class _LongOnlyEma(Strategy):  # type: ignore[misc]
    """Internal reference strategy used only by bounded backtest fixtures."""

    def __init__(
        self,
        *,
        instrument_id: NautilusInstrumentId,
        bar_type: BarType,
        quantity: Decimal,
        fast_period: int,
        slow_period: int,
        size_precision: int,
    ) -> None:
        super().__init__()
        self.instrument_id = instrument_id
        self.bar_type = bar_type
        self.quantity = quantity
        self.size_precision = size_precision
        self.fast = ExponentialMovingAverage(fast_period)
        self.slow = ExponentialMovingAverage(slow_period)
        self.decisions = 0
        self.signal_long = False
        self.instrument: CurrencyPair | None = None

    def on_start(self) -> None:
        instrument = self.cache.instrument(self.instrument_id)
        if not isinstance(instrument, CurrencyPair):
            self.stop()
            return
        self.instrument = instrument
        self.register_indicator_for_bars(self.bar_type, self.fast)
        self.register_indicator_for_bars(self.bar_type, self.slow)
        self.subscribe_bars(self.bar_type)

    def on_bar(self, bar: Bar) -> None:
        if not self.indicators_initialized() or self.instrument is None:
            return
        self.decisions += 1
        if self.fast.value > self.slow.value and not self.signal_long:
            self.signal_long = True
            if not self.portfolio.is_flat(self.instrument_id):
                return
            self.submit_order(
                self.order_factory.market(
                    instrument_id=self.instrument_id,
                    order_side=OrderSide.BUY,
                    quantity=Quantity(self.quantity, self.size_precision),
                )
            )
        elif self.fast.value < self.slow.value and self.signal_long:
            self.signal_long = False
            if not self.portfolio.is_net_long(self.instrument_id):
                return
            self.close_all_positions(self.instrument_id)


@dataclass(frozen=True)
class _Fill:
    side: OrderSide
    price: Decimal
    quantity: Decimal
    commission: Decimal
    timestamp_ns: int


def _nanoseconds(value: datetime) -> int:
    return int(value.timestamp()) * 1_000_000_000 + value.microsecond * 1_000


def _precision_quantum(precision: int) -> Decimal:
    return Decimal(1).scaleb(-precision)


def _fills(orders: list[Any]) -> list[_Fill]:
    result: list[_Fill] = []
    for order in orders:
        for event in order.events:
            if not all(hasattr(event, name) for name in ("last_px", "last_qty", "commission")):
                continue
            result.append(
                _Fill(
                    side=event.order_side,
                    price=event.last_px.as_decimal(),
                    quantity=event.last_qty.as_decimal(),
                    commission=event.commission.as_decimal(),
                    timestamp_ns=event.ts_event,
                )
            )
    return sorted(result, key=lambda item: item.timestamp_ns)


def _metrics(
    config: BacktestRunConfig,
    fills: list[_Fill],
) -> tuple[PerformanceMetrics, list[TradeOutcome]]:
    assert config.inline_data is not None
    bars = config.inline_data.bars
    currency = config.starting_balance.currency
    cash = config.starting_balance.amount
    position = Decimal(0)
    fill_index = 0
    entry: tuple[Decimal, Decimal, Decimal, datetime] | None = None
    trades: list[TradeOutcome] = []
    curve = [
        EquityPoint(
            at=config.dataset.period_start,
            equity=config.starting_balance,
            exposure=Money.zero(currency),
        )
    ]
    slippage_bps = config.costs.slippage.slippage_bps()

    for bar in bars:
        timestamp_ns = _nanoseconds(bar.ingested_at)
        while fill_index < len(fills) and fills[fill_index].timestamp_ns <= timestamp_ns:
            fill = fills[fill_index]
            notional = fill.price * fill.quantity
            slippage = notional * slippage_bps / Decimal(10_000)
            if fill.side is OrderSide.BUY:
                cash -= notional + fill.commission + slippage
                position += fill.quantity
                entry = (fill.price, fill.commission, slippage, bar.ingested_at)
            else:
                cash += notional - fill.commission - slippage
                position -= fill.quantity
                if entry is not None:
                    entry_price, entry_fee, entry_slippage, opened_at = entry
                    gross_pnl = (fill.price - entry_price) * fill.quantity
                    fees = entry_fee + fill.commission
                    net_pnl = gross_pnl - fees - entry_slippage - slippage
                    trades.append(
                        TradeOutcome(
                            instrument_id=bar.instrument_id.value,
                            opened_at=opened_at,
                            closed_at=bar.ingested_at,
                            net_pnl=Money(amount=net_pnl, currency=currency),
                            gross_pnl=Money(amount=gross_pnl, currency=currency),
                            fees=Money(amount=fees, currency=currency),
                            notional=Money(
                                amount=entry_price * fill.quantity + notional,
                                currency=currency,
                            ),
                        )
                    )
                    entry = None
            fill_index += 1
        exposure = position * bar.close
        curve.append(
            EquityPoint(
                at=bar.ingested_at,
                equity=Money(amount=cash + exposure, currency=currency),
                exposure=Money(amount=exposure, currency=currency),
            )
        )

    benchmark_return = bars[-1].close / bars[0].close - Decimal(1)
    total_fees = sum((fill.commission for fill in fills), start=Decimal(0))
    return (
        compute_metrics(
            curve=curve,
            trades=trades,
            total_fees=Money(amount=total_fees, currency=currency),
            benchmark_return=benchmark_return,
        ),
        trades,
    )


class NautilusBacktestAdapter:
    """Runs a Kavrigo backtest configuration on NautilusTrader."""

    name = ENGINE_NAME
    version = nautilus_trader.__version__

    def __init__(self, *, venue: str = "SIM", log_level: str = "ERROR") -> None:
        self._venue = venue
        self._log_level = log_level

    def preflight(self, config: BacktestRunConfig) -> list[str]:
        """Reasons this run must not execute.

        Checked before any engine work: a refusal should cost nothing and should never be
        reachable *after* a result exists.
        """
        return [
            f"{finding.code}: {finding.detail}" for finding in config.dataset.leakage_findings()
        ]

    def build_engine(self, config: BacktestRunConfig) -> NautilusBacktestEngine:
        """Construct a configured Nautilus engine for one run.

        Separated from :meth:`run` so the wiring — venue, account, fee, fill and latency models
        — can be asserted directly in tests without executing a simulation.
        """
        engine = NautilusBacktestEngine(
            config=BacktestEngineConfig(
                trader_id="KAVRIGO-001",
                logging=LoggingConfig(log_level=self._log_level),
            )
        )
        engine.add_venue(
            venue=Venue(self._venue),
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            # CASH rather than MARGIN: V1 is spot-only and non-custodial (ADR 0002), and a
            # margin account would let a simulation take leverage the product cannot.
            starting_balances=[
                NautilusMoney(config.starting_balance.amount, USDT),
            ],
            base_currency=None,
            fee_model=MakerTakerFeeModel(),
            fill_model=to_nautilus_fill_model(config.costs, random_seed=config.random_seed),
            latency_model=to_nautilus_latency_model(config.costs.latency),
        )
        return engine

    def bundle_for(
        self,
        config: BacktestRunConfig,
        *,
        spec_hash: str,
        prompt_hash: str,
        feature_manifest_hash: str,
        model_profile: str,
        resolved_model_identifier: str,
        container_image_digest: str,
        code_version: str,
        created_at: datetime | None = None,
    ) -> ReproducibilityBundle:
        """Assemble the reproducibility record for a run."""
        from kavrigo_backtest import cost_model_hash

        return ReproducibilityBundle(
            run_id=config.run_id,
            created_at=created_at or datetime.now(UTC),
            dataset_manifest_hash=config.dataset.manifest_hash,
            config_hash=config.config_hash,
            agent_version_id=config.agent_version_id,
            spec_hash=spec_hash,
            prompt_hash=prompt_hash,
            model_profile=model_profile,
            resolved_model_identifier=resolved_model_identifier,
            feature_set_version=config.dataset.feature_set_version,
            feature_manifest_hash=feature_manifest_hash,
            risk_policy_id=config.spec.risk_policy_ref,
            execution_policy_id=config.spec.execution_policy_ref,
            cost_model_hash=cost_model_hash(config.costs),
            random_seed=config.random_seed,
            engine_name=self.name,
            engine_version=self.version,
            container_image_digest=container_image_digest,
            code_version=code_version,
        )

    def _run_inline(
        self,
        config: BacktestRunConfig,
        *,
        bundle: ReproducibilityBundle,
        started_at: datetime,
    ) -> BacktestResult:
        assert config.inline_data is not None
        assert config.strategy is not None
        source_instrument = config.spec.universe.instruments[0]
        strategy_config = config.strategy
        internal_id = NautilusInstrumentId.from_str(
            f"{source_instrument.base}{source_instrument.quote}.{self._venue}"
        )
        price_quantum = _precision_quantum(strategy_config.price_precision)
        size_quantum = _precision_quantum(strategy_config.size_precision)
        engine = self.build_engine(config)
        try:
            instrument = CurrencyPair(
                instrument_id=internal_id,
                raw_symbol=Symbol(f"{source_instrument.base}{source_instrument.quote}"),
                base_currency=Currency.from_str(source_instrument.base),
                quote_currency=Currency.from_str(source_instrument.quote),
                price_precision=strategy_config.price_precision,
                size_precision=strategy_config.size_precision,
                price_increment=Price(
                    strategy_config.price_increment, strategy_config.price_precision
                ),
                size_increment=Quantity(
                    strategy_config.size_increment, strategy_config.size_precision
                ),
                min_quantity=Quantity(
                    strategy_config.size_increment, strategy_config.size_precision
                ),
                min_notional=NautilusMoney.from_str(
                    f"{config.costs.minimum_order_notional.amount} {source_instrument.quote}"
                    if config.costs.minimum_order_notional is not None
                    else f"1 {source_instrument.quote}"
                ),
                maker_fee=config.costs.fees.maker_bps / Decimal(10_000),
                taker_fee=config.costs.fees.taker_bps / Decimal(10_000),
                ts_event=0,
                ts_init=0,
            )
            engine.add_instrument(instrument)
            interval = config.inline_data.bars[0].interval_seconds
            if interval % 3_600 == 0:
                interval_text = f"{interval // 3_600}-HOUR"
            elif interval % 60 == 0:
                interval_text = f"{interval // 60}-MINUTE"
            else:
                interval_text = f"{interval}-SECOND"
            bar_type = BarType.from_str(f"{internal_id}-{interval_text}-LAST-EXTERNAL")
            bars = [
                Bar(
                    bar_type=bar_type,
                    open=Price(bar.open.quantize(price_quantum), strategy_config.price_precision),
                    high=Price(bar.high.quantize(price_quantum), strategy_config.price_precision),
                    low=Price(bar.low.quantize(price_quantum), strategy_config.price_precision),
                    close=Price(bar.close.quantize(price_quantum), strategy_config.price_precision),
                    volume=Quantity(
                        bar.volume.quantize(size_quantum), strategy_config.size_precision
                    ),
                    ts_event=_nanoseconds(bar.event_time),
                    ts_init=_nanoseconds(bar.ingested_at),
                )
                for bar in config.inline_data.bars
            ]
            raw_quantity = strategy_config.trade_notional.amount / config.inline_data.bars[0].close
            quantity = (raw_quantity // strategy_config.size_increment) * (
                strategy_config.size_increment
            )
            strategy = _LongOnlyEma(
                instrument_id=internal_id,
                bar_type=bar_type,
                quantity=quantity,
                fast_period=strategy_config.fast_period,
                slow_period=strategy_config.slow_period,
                size_precision=strategy_config.size_precision,
            )
            engine.add_data(bars)
            engine.add_strategy(strategy)
            # NautilusTrader 1.231.0 calls the deprecated ``Timestamp.utcnow`` internally.
            # Keep the suppression narrow so all other warnings still fail the test suite.
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Timestamp.utcnow is deprecated.*",
                )
                engine.run()
            orders = list(engine.cache.orders())
            fills = _fills(orders)
            metrics, _ = _metrics(config, fills)
            return BacktestResult(
                run_id=config.run_id,
                workspace_id=config.workspace_id,
                status=RunStatus.COMPLETED,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                period_start=config.dataset.period_start,
                period_end=config.dataset.period_end,
                metrics=metrics,
                cost_model=config.costs,
                bundle=bundle,
                optimism_warnings=config.costs.optimism_warnings,
                leakage_findings=[],
                decisions_evaluated=strategy.decisions,
                orders_submitted=len(orders),
                # This diagnostic does not replay Kavrigo's deterministic risk engine. A
                # simulator rejection is not a risk rejection and must not be relabeled as one.
                orders_rejected_by_risk=0,
                limitations=[
                    "bar_data_execution_limits_intrabar_realism",
                    "deterministic_risk_policy_not_replayed",
                    "inline_fixture_not_catalog_dataset",
                    "provider_entitlement_not_verified",
                    "reference_strategy_not_agent_runtime",
                ],
            )
        finally:
            engine.dispose()

    def run(self, config: BacktestRunConfig, *, bundle: ReproducibilityBundle) -> BacktestResult:
        """Execute a run, or refuse it.

        Bounded inline fixtures can execute the internal reference strategy. Runs without data
        preserve the earlier engine-wiring diagnostic and report zero decisions; the durable
        workflow refuses to treat those diagnostics as successful research.
        """
        started_at = datetime.now(UTC)

        findings = self.preflight(config)
        if findings:
            return refuse(
                config,
                reason=(
                    "Dataset is not point-in-time safe; running it would produce a figure "
                    "derived from information the strategy could not have had."
                ),
                started_at=started_at,
                bundle=bundle,
                findings=findings,
            )

        if config.inline_data is not None:
            return self._run_inline(config, bundle=bundle, started_at=started_at)

        engine = self.build_engine(config)
        try:
            # No data and no strategy yet, so nothing is simulated. Constructing and disposing
            # the engine still proves the venue, account, fee, fill and latency wiring is
            # accepted by this Nautilus version.
            return BacktestResult(
                run_id=config.run_id,
                workspace_id=config.workspace_id,
                status=RunStatus.COMPLETED,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                period_start=config.dataset.period_start,
                period_end=config.dataset.period_end,
                metrics=_empty_metrics(config),
                cost_model=config.costs,
                bundle=bundle,
                optimism_warnings=config.costs.optimism_warnings,
                leakage_findings=[],
                decisions_evaluated=0,
                orders_submitted=0,
                orders_rejected_by_risk=0,
            )
        finally:
            engine.dispose()


def _empty_metrics(config: BacktestRunConfig) -> PerformanceMetrics:
    """Metrics for a run that placed no trades.

    A flat equity curve with zero trades. Every ratio reports unavailable, which is the honest
    description of a run with no activity — not a Sharpe of zero.
    """
    from kavrigo_backtest import EquityPoint, compute_metrics
    from kavrigo_domain import Money

    flat = [
        EquityPoint(
            at=config.dataset.period_start,
            equity=config.starting_balance,
            exposure=Money.zero(config.starting_balance.currency),
        ),
        EquityPoint(
            at=config.dataset.period_end,
            equity=config.starting_balance,
            exposure=Money.zero(config.starting_balance.currency),
        ),
    ]
    return compute_metrics(
        curve=flat,
        trades=[],
        total_fees=Money.zero(config.starting_balance.currency),
        benchmark_return=None,
    )


def default_seed() -> int:
    return 0


def _decimal(value: str) -> Decimal:  # pragma: no cover - convenience for callers
    return Decimal(value)
