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

Each new risk-gated result also includes a `reference-risk-audit-v1` journal. Its ordered receipts
retain each available request (decision, evidence, snapshot, allocation, intent and simulated
book), portfolio, supervisor controls and evaluator record. `handed_off_quantity` is the
quantity released to the reference strategy, not a fill confirmation. A failed handoff can retain
an approved evaluator record while showing no released quantity. Unavailable inputs remain
absent and exceptions are represented by safe codes without exception text.

The journal verifies input hashes, identity, sequence, unique intents, quantity ceilings and
aggregate counts. Re-evaluating its frozen inputs reproduces the evaluator records. Receipts
are diagnostic data and cannot be submitted as execution permits. A no-signal run carries an
empty hashed journal; older results without a journal have unavailable audit detail.

Collection is capped at 5,000 receipts and 8 MB of serialized journal data. If the adapter cannot
retain a complete journal, it stops further handoffs and refuses the run without metrics instead
of returning a truncated history. Full data is saved in tenant-scoped PostgreSQL stage output;
Temporal history retains only the stage reference/hash. These backend artifacts do not yet have
a dedicated product UI. See [ADR 0042](../adr/0042-reference-backtest-risk-receipts.md).
