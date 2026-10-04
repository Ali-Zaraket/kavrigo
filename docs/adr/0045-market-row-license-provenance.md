# ADR 0045: Preserve licence provenance on persisted market rows

- **Status:** Accepted for the local ingestion schema
- **Date:** 2026-10-04
- **Spec reference:** `MASTER_BUILD_SPEC.md` §§8.3, 14, 61

## Context

The existing ClickHouse market tables recorded `provider` but not the specific `license_ref`.
Provider names are insufficient to identify which raw rows must be removed when a contract or
subscription ends. The entitlement ledger requires an exact licence reference for evidence, but
the analytical row writer did not carry one. This was a launch-blocking gap for licensed data.

## Options and decision

We considered inferring the licence from provider and ingestion time at deletion time. That
depends on mutable external records and can misidentify rows when a provider changes terms.
Instead, the ClickHouse sink now requires a nonempty licence reference and writes it on each
trade, quote and candle row. Existing local tables receive an additive column with an empty
default, making legacy rows explicitly unqualified rather than inventing provenance.

## Security, operations and rollback

The field is an internal identifier, never an API key or contract body. It enables targeted
deletion, but deletion itself, retention timing, data exports and backup erasure still need a
provider-specific operational runbook before production use. The writer refuses an empty ref;
the current public sampler uses a count-only sink and remains ephemeral. No production provider
grant is created by this change. Rolling back the writer would reintroduce untraceable rows and
must not be done after licensed ingestion begins.

The local ClickHouse bootstrap uses idempotent `ALTER TABLE ADD COLUMN IF NOT EXISTS` statements
for existing volumes. This is not a managed ClickHouse migration plan; that plan remains part of
the hosted data-path gate.
