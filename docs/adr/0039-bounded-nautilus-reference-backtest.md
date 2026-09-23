# ADR 0039: Bounded Nautilus reference backtest

- **Status:** Accepted for local scientific and workflow validation
- **Date:** 2026-09-23
- **Deciders:** Principal engineering agent
- **Spec reference:** `MASTER_BUILD_SPEC.md` §§12.2–12.6 and 13.2

## Context

Kavrigo already pins NautilusTrader and records reproducibility, cost, leakage and metric
contracts, but its adapter has no historical data or strategy. A clean run therefore produces
zero decisions and the durable workflow correctly refuses it. Paper promotion cannot rely on
that empty artifact.

The production catalog and licensed BTC/ETH dataset are not available yet. The smallest useful
step is a bounded immutable bar fixture that proves real engine data, strategy, order, fill,
cost, benchmark and workflow behavior without presenting synthetic performance as agent evidence.

## Options considered

1. **Keep the zero-decision adapter** — safe, but leaves the backtest workflow unexercised.
2. **Calculate a toy result outside NautilusTrader** — quick, but bypasses the selected engine's
   event ordering and cash-account fill lifecycle.
3. **Run a built-in bidirectional EMA example** — demonstrates the engine but can open shorts,
   which conflicts with Kavrigo's spot-only cash scope.
4. **Add one internal long-only reference strategy and bounded inline bars** — exercises the
   pinned engine while keeping the fixture explicit, immutable and non-promotable.

## Evidence

NautilusTrader's official documentation says historical data advances the backtest clock and
drives callbacks, and describes adding instruments, strategies and data to the low-level engine.
It also states that bars have less execution detail than quotes, trades or order-book data. The
installed 1.231.0 package was inspected and exercised because the current 2.x documentation
warns that its Python API differs from 1.x.

A September 2026 upstream issue reports instrument-registration-order-dependent market fills in
multi-instrument cash backtests on 1.231.0. This slice therefore permits exactly one instrument
per engine run. BTC and ETH fixtures run separately until the upstream behavior is resolved or a
verified workaround is adopted.

- [Backtest APIs and runs](https://nautilustrader.io/docs/latest/concepts/backtesting/apis-and-runs/)
- [Backtest data and venue fidelity](https://nautilustrader.io/docs/latest/concepts/backtesting/data-and-venues/)
- [Upstream multi-instrument fill issue](https://github.com/nautechsystems/nautilus_trader/issues/4891)

## Decision

Add `BacktestBar`, `InlineBarDataset` and `LongOnlyEmaStrategy` contracts. Inline data is capped
at 5,000 bars, includes event and ingestion times, and must be unique, replay-ordered and bound
by content hash to a matching point-in-time dataset-manifest source. Configuration binds the
strategy, benchmark, instrument, cost model, seed and data hash.

The Nautilus adapter translates one BTC-USDT or ETH-USDT fixture to an internal SIM spot
instrument, feeds bars with event and ingestion timestamps, and runs a long-only EMA strategy in
a cash account. Orders and fills come from Nautilus. Kavrigo reconstructs an exact Decimal equity
curve from fill prices, commissions, configured slippage and bar marks, then computes existing
after-cost and benchmark-relative metrics.

The result always records these limitations: inline data rather than the catalog, bar-level
execution fidelity, no provider-entitlement verification, an internal reference strategy rather
than the agent runtime, and no deterministic risk-policy replay. A result with any limitation is
not publishable and cannot be paper-activation evidence.

## Security and compliance impact

No user code, model tool, provider connection, credential, order gateway or live venue is added.
Fixtures are immutable inputs inside the run definition. Hash mismatch, late/future knowledge,
manifest mismatch, inconsistent precision, missing benchmark, multiple instruments and unsafe
dataset findings fail before execution.

Synthetic fixture results must retain their limitations in every API or UI projection. A
`license_ref` in a manifest is provenance only; this adapter cannot verify legal entitlement.

## Operational impact

Inline runs are intentionally small and memory-resident. Each independent run creates and
disposes a fresh engine. The single-instrument limit avoids a known upstream correctness risk.
Pandas warnings emitted inside pinned Nautilus 1.x are an upstream compatibility signal and do
not change the artifact.

## Migration and rollback

The contracts are additive and need no database migration because durable run definitions and
stage outputs are JSON documents. Old zero-decision configurations remain valid. Rollback removes
the optional inline data and strategy fields and returns the adapter to empty runs; stored JSON
artifacts must remain readable before deploying such a rollback outside local development.

## Consequences

The durable backtest workflow can now complete a real engine run with decisions, orders, fills,
costs and a benchmark. It still does not prove an AI agent's edge or satisfy promotion. The next
backtest slice must load licensed catalog data, replay the actual agent decision and deterministic
risk policies, add out-of-sample separation, and only then feed a promotion gate.
