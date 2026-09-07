# ADR 0009: Temporal Cloud for durable workflows

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §13.2, §19

## Context

Agent evaluation, backtests, reconciliation, scheduled evaluation and promotion are long-running, retry-heavy processes that must survive process restarts and be inspectable after the fact.

## Options considered

1. **Celery/cron plus bespoke state tables** — familiar, and re-implements durable execution badly.
2. **Temporal Cloud** — durable execution, retries, timers, versioning, history as first-class.
3. **Step Functions** — durable, but weaker fit for Python-heavy long-running quant workloads.

## Decision

Option 2 for durable business workflows. Market ticks do **not** flow through Temporal — Redpanda carries streams, Temporal carries durable workflows. Backtest, agent evaluation, reconciliation and data-health workflows are Temporal workflows (§19).

## Security and compliance impact

Workflow history is an operational record, not the audit ledger; the immutable trade audit ledger remains ours (§25). Workflow inputs must not carry secrets.

## Consequences

Easier: recoverable asynchronous work and reconciliation. Harder: a vendor dependency on the durable-execution path, and workflow versioning discipline.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
