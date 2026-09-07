# ADR 0008: ClickHouse for analytical and time-series data

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §16.7, §39

## Context

Market events, feature history, decision analytics and P&L series are append-heavy, high-cardinality and queried multi-dimensionally. Putting them in the OLTP database would couple analytical load to authoritative transactional state.

## Options considered

1. **TimescaleDB inside PostgreSQL** — one system, but ties analytical scale to the control-plane database.
2. **ClickHouse Cloud** — purpose-built for large append-heavy event/time-series analytics.
3. **S3 + query engine only** — cheap, too slow for interactive product analytics.

## Decision

Option 2. ClickHouse Cloud is the analytical store and doubles as the historical feature store; Valkey holds ephemeral latest features; S3/Parquet holds frozen backtest/training datasets. No standalone feature-store product in V1 (§39).

## Security and compliance impact

Analytical queries must carry tenant constraints explicitly — ClickHouse has no RLS equivalent in our usage. Retention must respect provider licence terms on raw data storage (§8.3).

## Consequences

Easier: interactive analytics at event scale. Harder: two stores to keep consistent; duplication of authoritative state requires an explicit projection/reconciliation model.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
