# ADR 0042: Per-signal risk receipts for reference backtests

- **Status:** Accepted for local validation
- **Date:** 2026-09-27
- **Spec reference:** `MASTER_BUILD_SPEC.md` §§12.2, 25 and 26.2

## Context and options

ADR 0041 records risk counts and a configuration hash but discards the evaluated request and
portfolio. Counts alone cannot explain a particular resized or rejected signal. Keeping only
telemetry would also make optional export infrastructure the authority for trading evidence.

Use typed receipts in the existing durable backtest result, rather than a new audit database or
duplicated request schema. `kavrigo-backtest` may import `kavrigo-risk` contracts; that dependency
is acyclic (risk depends on runtime and domain, neither depends on backtest). The contracts
remain independent of Nautilus and do not include a broker permit or exchange capability.

## Decision

Each attempted reference order records its sequence, frozen time, run/workspace/version,
instrument, side, replay hash, available risk request, portfolio, supervisor controls, evaluator
record, safe reason codes and quantity handed to the reference strategy. Missing inputs remain
absent on failure; the receipt never fabricates a successful evaluation. A handoff is explicitly
distinct from a submitted or filled order.

An ordered journal has a canonical content hash and validates receipt identity, input hashes,
result counts and reason totals. New risk-gated runs always include a journal, including an
empty one for no-signal runs. Historical results without journals remain readable.

Bound journal collection by receipt count and serialized byte size below the existing 10 MB
stage-output ceiling. Exhaustion disables further handoffs and refuses the entire run without
performance metrics; never silently truncate the audit trail. Full receipts stay in tenant-scoped
PostgreSQL stage output. Temporal continues carrying only `StageRef` values.

## Evidence

Pydantic documents recursive typed model serialization and JSON round trips. Temporal documents
payload and history limits; full journals therefore stay outside workflow history.

- [Pydantic serialization](https://docs.pydantic.dev/latest/concepts/serialization/)
- [Temporal execution limits](https://docs.temporal.io/workflow-execution/limits)

## Security and operational impact

The journal contains simulated account/evidence data and uses the existing tenant authorization,
RLS and immutable stage hash. It is not exported to logs or OTel. Exceptions become stable reason
codes without exception text. Hashes detect corruption; they are not signatures and do not confer
execution authorization. Synthetic data and promotion limitations remain mandatory.

## Migration and rollback

Optional result fields require no database migration. Old receipts remain readable with absent
audit detail. Rollback removes new journal creation but must not reinterpret historical absence
as a verified empty journal. The new dependency adds no external package or provider connection.
