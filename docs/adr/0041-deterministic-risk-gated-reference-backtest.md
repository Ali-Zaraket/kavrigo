# ADR 0041: Deterministic-risk-gated reference backtest

- **Status:** Accepted for local validation
- **Date:** 2026-09-23
- **Deciders:** Principal engineering agent
- **Spec reference:** `MASTER_BUILD_SPEC.md` §§11, 12.2–12.5 and 32.3

## Context

ADRs 0039 and 0040 proved deterministic Nautilus orders, fills, metrics and durable execution,
but the diagnostic strategy submitted orders without replaying Kavrigo's deterministic risk
engine. A result could therefore exercise execution behavior that the corresponding versioned
policies would reject. Removing that limitation requires the real risk evaluator to run before
every simulated order and requires its inputs to come from point-in-time engine state.

The existing public Binance reference fixture is quoted in USDT. Kavrigo's V1 risk policy uses
USD as the authoritative base currency. Silently treating USDT as USD would erase a material
currency assumption, so the risk-gated reference fixture needs an explicit synthetic USD venue.

## Evidence

NautilusTrader 1.231.0 is still pinned. Its current official documentation states that the
backtest engine processes market data through the exchange before invoking strategy handlers,
and that `Portfolio` exposes account, balance, position, realized/unrealized P&L and open-order
state. Those semantics let the adapter construct risk state from the simulator rather than from
a parallel accounting model.

- [NautilusTrader backtesting](https://nautilustrader.io/docs/latest/concepts/backtesting/)
- [NautilusTrader backtest data and venues](https://nautilustrader.io/docs/latest/concepts/backtesting/data-and-venues/)
- [NautilusTrader portfolio](https://nautilustrader.io/docs/latest/concepts/portfolio/)
- [NautilusTrader accounting](https://nautilustrader.io/docs/latest/concepts/accounting/)

## Options considered

1. Keep risk outside the reference run and label the limitation. This preserves the previous
   behavior but cannot prove rejected intents are stopped before execution.
2. Reimplement a reduced risk formula inside the Nautilus adapter. This would create a second
   authority whose behavior could drift from the production risk service.
3. Construct the real `RiskRequest` from Nautilus state and invoke `LocalRiskSession` before
   each order. This preserves one deterministic evaluator and gives the adapter only a
   translation role.

## Decision

Use option 3 for an explicitly bounded `reference-risk-replay-v1` path.

The immutable run configuration binds the exact approved local `AgentVersion`, global,
workspace and agent risk policies and their hashes, execution policy, network mapping and
supervisor controls. It becomes part of the run configuration hash and reproducibility bundle.
The shared execution-policy contract lives in `kavrigo_domain` so backtest, risk and paper
components use the same fixed-point assumptions without a package dependency cycle.

Before each EMA reference signal can submit an order, the adapter constructs a frozen market
snapshot, structured diagnostic decision, evidence set, allocation and `OrderIntent`. It derives
cash, position, realized and unrealized P&L, open orders and marked equity from Nautilus-owned
state. Peak equity is observed on every closed bar. The real deterministic evaluator must
approve the request and issue a one-time handoff permit; otherwise no order reaches Nautilus.
Sell sizing uses the risk engine's fixed-point worst-price arithmetic so the approved quantity
closes the intended position without floating-point or rounding drift.

The path is deliberately restricted to:

- one synthetic `*-USD.SIM` instrument and USD cash;
- one UTC day, until daily-P&L rollover is implemented;
- candle freshness only, because OHLCV bars cannot prove book or trade freshness;
- zero minimum fee and zero ADV-impact term, until both are reproduced by risk sizing;
- the deterministic EMA diagnostic, not the versioned agent runtime.

Runs record risk evaluations, approvals, rejection reason counts and the risk-replay hash.
Configuration or bundle mismatches refuse before engine construction. The older USDT reference
path remains available and retains the `deterministic_risk_policy_not_replayed` limitation.

## Security and compliance impact

The model cannot modify policies or supervisor state, and the adapter receives no exchange
credential or raw execution capability. Unknown account state and risk exceptions fail closed.
Kill switches and stale-state checks reject before order submission. All inputs are synthetic;
this decision grants no provider right and does not make a result publishable, promotable or
eligible for paper activation.

## Operational impact

The durable workflow persists the risk counters and replay hash in its result and stage receipt.
A rejection is a completed, explainable simulation outcome rather than a workflow failure.
Current one-day and cost-model guards avoid producing a plausible result from semantics that
the adapter does not yet reproduce.

## Migration and rollback

The run and result contracts add optional fields and remain JSON-compatible, so no database
migration is required. Removing `risk_replay` returns a run to the existing USDT reference path
and restores its risk-not-replayed limitation. Stored risk-gated definitions would refuse if the
adapter no longer understood the replay contract.

## Consequences

Kavrigo can prove that a deterministic risk rejection never reaches the simulated venue and can
replay approved reference orders with version-bound policies. It still cannot claim that the
actual agent runtime produced the decisions or that synthetic bar evidence establishes an edge.
Licensed point-in-time data, the runtime decision graph, multi-day accounting and promotion-grade
evaluation remain separate work.
