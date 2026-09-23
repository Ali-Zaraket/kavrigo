# Frozen backtest catalog

The local worker reads reference datasets from `.local/backtest-catalog`, mounted read-only in
the container. A run stores a relative object key, exact SHA-256 byte hash, row count, instrument
and bar interval. It cannot choose an arbitrary machine path.

The `parquet-bars-v1` schema is exact:

| Column | Arrow type |
|---|---|
| `instrument_id` | non-null UTF-8 string |
| `interval_seconds` | non-null int64 |
| `open`, `high`, `low`, `close`, `volume` | non-null decimal128(38,18) |
| `event_time`, `ingested_at` | non-null UTC timestamp in microseconds |

Before Nautilus starts, the loader verifies the file-size bound, byte hash, Parquet page
checksums, schema, row count, instrument, interval, replay ordering, OHLC consistency, decimal
precision, manifest source binding and point-in-time bounds. Any failure produces a refused run
without exposing the catalog path.

This local catalog is plumbing, not a licensed dataset. It contains no provider data by default,
does not prove provider entitlement and cannot make a reference result publishable or eligible
for paper activation. See [ADR 0040](../adr/0040-frozen-local-parquet-backtest-catalog.md).
