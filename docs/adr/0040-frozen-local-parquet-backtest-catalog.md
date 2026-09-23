# ADR 0040: Frozen local Parquet backtest catalog

- **Status:** Accepted for local dataset-boundary validation
- **Date:** 2026-09-23
- **Deciders:** Principal engineering agent
- **Spec reference:** `MASTER_BUILD_SPEC.md` §§8.6, 12.2–12.5 and 17.3

## Context

ADR 0039 proved the Nautilus and Temporal path with inline bars, but embedding all historical
rows in a durable run definition does not scale and does not match the production S3/Parquet
design. The application still needs a frozen object boundary before licensed provider data can
be loaded safely.

A run-selected host path would be unsafe: it could read arbitrary worker files, change between
verification and parsing, or point at a dataset whose bytes do not match the manifest. A Parquet
file also needs an exact logical schema; accepting inferred floats would violate the fixed-point
money rule.

## Evidence

Apache Arrow 25.0.1 documents `ParquetFile` metadata, Arrow-schema inspection, bounded column
reads and page-checksum verification. It also documents reading a single file from a buffer.
Kavrigo uses those APIs on the same in-memory bytes it hashes, rather than asking Arrow to reopen
a mutable path.

- [Apache Arrow `ParquetFile`](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetFile.html)
- [Apache Arrow Parquet guide](https://arrow.apache.org/docs/python/parquet.html)

## Decision

Add a `ParquetBarDatasetRef` containing a relative object key, exact byte hash, row count,
instrument and interval. The worker, not the run payload, owns the catalog root. Local Compose
mounts `.local/backtest-catalog` read-only at `/var/lib/kavrigo/backtest-catalog`.

`LocalParquetBarCatalog` resolves the key beneath that root, reads at most 128 MiB, hashes the
exact bytes, verifies Parquet checksums and bounded metadata, requires the canonical schema, and
then validates every row through `BacktestBar`. Decimal OHLCV columns are `decimal128(38,18)`;
event and ingestion timestamps are UTC microseconds. The run config binds the same hash and row
count to a dataset-manifest source and rechecks point-in-time bounds before engine construction.

Inline fixtures remain supported for small unit and workflow tests. A local catalog result
replaces the inline-data limitation with `local_parquet_catalog_not_production_snapshot`; all
other reference-strategy limitations remain.

## Security and compliance impact

Object keys allow a conservative ASCII relative-path subset and cannot contain traversal,
absolute paths or Windows separators. Symlinks resolving outside the configured root are
rejected. Hashing and parsing use one byte string, closing the file-replacement gap. The Compose
mount is read-only and the worker fails startup if its configured root is absent.

This catalog does not grant provider rights. It does not download, seed or persist any external
market data, and `provider_entitlement_not_verified` remains mandatory. A manifest
`license_ref` is provenance, not proof of entitlement.

## Operational impact

The local loader is intentionally single-file and capped at 5,000 bars per reference run. It
uses single-threaded column reads for deterministic local validation. Production S3 access will
implement the same `BarCatalog` protocol with immutable version IDs, authenticated service
access, range/scan budgets and entitlement enforcement.

## Migration and rollback

The run contract is additive and stored as JSON, so no database migration is required. Removing
the optional catalog reference and worker mount returns behavior to inline-only runs. Previously
stored catalog jobs would then refuse with `catalog_unconfigured`, rather than reading from an
untrusted fallback path.

## Consequences

Kavrigo can execute a deterministic reference backtest from a frozen, externally stored Parquet
object without embedding rows in the workflow payload. Licensed provider ingestion, production
object storage, actual agent/risk replay and promotion-grade datasets remain separate gates.
