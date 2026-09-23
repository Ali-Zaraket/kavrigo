# Deterministic reference backtest fixtures

Kavrigo's local reference backtest exercises the pinned NautilusTrader engine with a small,
hash-addressed BTC-USDT or ETH-USDT bar fixture. It validates the scientific and durable workflow
plumbing; it is not evidence that an AI agent has an edge.

Every fixture records event time, ingestion time, OHLCV values, interval, instrument and a
canonical content hash. The hash must match a source in the point-in-time dataset manifest, the
manifest must cover the final ingestion time, and every run pins the agent version, cost model,
benchmark, seed, code, engine and feature versions.

The internal strategy is a long-only fast/slow EMA diagnostic. NautilusTrader owns cash-account
orders and fills. Kavrigo calculates Decimal metrics from those fills, explicit fees and
slippage, and reports the instrument's buy-and-hold return as the benchmark. Ratios remain
unavailable when the sample is too small.

Reference results carry five mandatory limitations:

- bar data cannot prove intrabar spread, depth, queue or price ordering;
- the deterministic risk policy is not replayed;
- data is an inline fixture rather than a licensed catalog snapshot;
- provider entitlement is not verified;
- the internal reference strategy is not the versioned agent runtime.

Any limitation makes the artifact non-publishable and ineligible for paper activation. BTC and
ETH run in separate engines because pinned NautilusTrader 1.231.0 has a reported multi-instrument
fill-order dependency. See [ADR 0039](../adr/0039-bounded-nautilus-reference-backtest.md).
