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

from datetime import UTC, datetime
from decimal import Decimal

import nautilus_trader
from nautilus_trader.backtest.engine import BacktestEngine as NautilusBacktestEngine
from nautilus_trader.backtest.models import MakerTakerFeeModel
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money as NautilusMoney

from kavrigo_backtest import (
    BacktestResult,
    BacktestRunConfig,
    ReproducibilityBundle,
    RunStatus,
    refuse,
)
from kavrigo_nautilus.translation import to_nautilus_fill_model, to_nautilus_latency_model

__all__ = ["ENGINE_NAME", "NautilusBacktestAdapter"]

ENGINE_NAME = "nautilus_trader"


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

    def run(self, config: BacktestRunConfig, *, bundle: ReproducibilityBundle) -> BacktestResult:
        """Execute a run, or refuse it.

        The strategy layer is not wired yet: the agent runtime that produces decisions is step 10
        of the build sequence. What works today is the engine boundary — configuration,
        preflight refusal, cost translation and the reproducibility record. A run with no
        strategy is reported as ``COMPLETED`` with zero decisions rather than being dressed up
        as a result.
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


def _empty_metrics(config: BacktestRunConfig):  # type: ignore[no-untyped-def]
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
