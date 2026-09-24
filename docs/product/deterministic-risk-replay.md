# Deterministic risk replay

The bounded reference backtest can route every synthetic USD order signal through Kavrigo's real
deterministic risk evaluator before NautilusTrader receives it. The run binds an approved local
agent version, exact global/workspace/agent policy hashes, execution assumptions, network mapping
and supervisor controls. Those inputs are immutable and included in the run hash.

At each signal, the adapter reads cash, position, realized and unrealized P&L and open orders from
Nautilus. It marks equity from the closed bar and tracks peak equity on every bar. From the same
point-in-time input it creates a structured diagnostic decision, frozen evidence, allocation and
order intent. An order is submitted only after `LocalRiskSession` approves it and issues a
one-time handoff permit. Rejections are counted by machine-readable reason and never reach the
simulated venue.

This is a narrow validation path:

- the instrument must be synthetic USD spot on `SIM`;
- bars must fit within one UTC date;
- policies may require candle freshness only;
- minimum fees and ADV impact must be zero;
- the EMA diagnostic creates the decision and evidence, not the versioned agent runtime.

The result records evaluation and approval counts, reason counts and the exact replay hash. It
keeps the bar-realism, provider-entitlement, synthetic/local-dataset and reference-strategy
limitations, so it remains non-publishable and cannot activate paper trading. See
[ADR 0041](../adr/0041-deterministic-risk-gated-reference-backtest.md).
