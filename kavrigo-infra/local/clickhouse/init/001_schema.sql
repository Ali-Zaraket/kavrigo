-- Kavrigo analytical store bootstrap (local development only).
--
-- ClickHouse holds high-volume append-only event and feature history (ADR 0008). It is not
-- authoritative for orders, positions or balances; those live in PostgreSQL and are reconciled
-- against the venue.
--
-- ClickHouse has no row-level security in our usage, so every tenant-scoped query must carry an
-- explicit workspace predicate (MASTER_BUILD_SPEC.md §20).

CREATE DATABASE IF NOT EXISTS kavrigo;

-- Normalized public trades. Prices and quantities are Decimal, never Float: an analytical store
-- that disagrees with the ledger is a reconciliation problem waiting to happen.
CREATE TABLE IF NOT EXISTS kavrigo.market_trades
(
    venue           LowCardinality(String),
    instrument_id   LowCardinality(String),   -- canonical: BTC-USDT.BINANCE
    event_time      DateTime64(3, 'UTC'),
    ingested_at     DateTime64(3, 'UTC'),
    price           Decimal(38, 18),
    quantity        Decimal(38, 18),
    aggressor       Enum8('unknown' = 0, 'buy' = 1, 'sell' = 2),
    venue_trade_id  String,
    sequence        Int64,
    provider        LowCardinality(String),
    schema_version  LowCardinality(String)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (venue, instrument_id, event_time)
TTL toDateTime(event_time) + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;
-- TTL is a placeholder. Real retention is dictated by each provider's licence terms
-- (MASTER_BUILD_SPEC.md §8.3), not by convenience.

-- Top-of-book quotes. `has_venue_time` records whether the venue supplied its own timestamp:
-- Binance's bookTicker does not, so `event_time` there is arrival time. Without the flag a
-- consumer could not tell venue latency from our own, and would understate staleness.
CREATE TABLE IF NOT EXISTS kavrigo.market_quotes
(
    venue           LowCardinality(String),
    instrument_id   LowCardinality(String),
    event_time      DateTime64(3, 'UTC'),
    ingested_at     DateTime64(3, 'UTC'),
    has_venue_time  UInt8,
    bid_price       Decimal(38, 18),
    bid_size        Decimal(38, 18),
    ask_price       Decimal(38, 18),
    ask_size        Decimal(38, 18),
    spread_bps      Decimal(38, 18),
    sequence        Int64,
    provider        LowCardinality(String),
    schema_version  LowCardinality(String)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (venue, instrument_id, event_time)
TTL toDateTime(event_time) + INTERVAL 90 DAY;

-- OHLCV bars. `is_closed` is load-bearing: a backtest that consumes an unclosed bar as final
-- has look-ahead bias, because its close, high and low can all still change
-- (MASTER_BUILD_SPEC.md 12.3). Queries feeding historical runs must filter on it.
CREATE TABLE IF NOT EXISTS kavrigo.market_candles
(
    venue                 LowCardinality(String),
    instrument_id         LowCardinality(String),
    interval              LowCardinality(String),
    event_time            DateTime64(3, 'UTC'),
    ingested_at           DateTime64(3, 'UTC'),
    open_time             DateTime64(3, 'UTC'),
    close_time            DateTime64(3, 'UTC'),
    open                  Decimal(38, 18),
    high                  Decimal(38, 18),
    low                   Decimal(38, 18),
    close                 Decimal(38, 18),
    volume                Decimal(38, 18),
    quote_volume          Decimal(38, 18),
    taker_buy_base_volume Decimal(38, 18),
    trade_count           UInt32,
    is_closed             UInt8,
    provider              LowCardinality(String),
    schema_version        LowCardinality(String)
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(open_time)
ORDER BY (venue, instrument_id, interval, open_time);
-- Note that `provider` is NOT part of the ORDER BY key. Two rows sharing (venue, instrument,
-- interval, open_time) are the same bar as far as the engine is concerned, and the newer
-- ingested_at wins. That is the intent for a bar reissued as it forms, and it means a second
-- writer cannot be distinguished from a correction.
-- ReplacingMergeTree because a bar is re-sent as it forms and again when it closes: the newest
-- version of a given (venue, instrument, interval, open_time) is the one that counts. Trades
-- and quotes stay on plain MergeTree — they are immutable facts, not evolving state.

-- Versioned feature history, doubling as the offline feature store (ADR 0008, §39).
CREATE TABLE IF NOT EXISTS kavrigo.features
(
    instrument_id        LowCardinality(String),
    feature_set_version  LowCardinality(String),
    as_of                DateTime64(3, 'UTC'),
    computed_at          DateTime64(3, 'UTC'),
    feature_name         LowCardinality(String),
    feature_value        Decimal(38, 18),
    content_hash         String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(as_of)
ORDER BY (instrument_id, feature_set_version, feature_name, as_of);

-- Decision analytics. Tenant-scoped: every query must filter on workspace_id.
CREATE TABLE IF NOT EXISTS kavrigo.decisions
(
    workspace_id       String,
    agent_version_id   String,
    decision_id        String,
    snapshot_id        String,
    instrument_id      LowCardinality(String),
    decided_at         DateTime64(3, 'UTC'),
    market_regime      LowCardinality(String),
    state              LowCardinality(String),
    proposed_action    LowCardinality(String),
    proposed_notional  Decimal(38, 18),
    notional_currency  LowCardinality(String),
    confidence         Float32,
    uncertainty        Float32,
    risk_decision      LowCardinality(String),
    reason_codes       Array(LowCardinality(String)),
    evidence_count     UInt16,
    contradicting_evidence_count UInt16,
    model_cost_usd     Decimal(18, 8)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(decided_at)
ORDER BY (workspace_id, agent_version_id, decided_at);
-- Abstentions are recorded like any other decision: NO_TRADE is an outcome to measure, not an
-- absence of one.

-- Data-source health, feeding the freshness indicators the UI must show (§31).
CREATE TABLE IF NOT EXISTS kavrigo.source_health
(
    provider        LowCardinality(String),
    stream          LowCardinality(String),
    observed_at     DateTime64(3, 'UTC'),
    lag_ms          UInt32,
    sequence_gaps   UInt32,
    reconnects      UInt16,
    is_stale        UInt8
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(observed_at)
ORDER BY (provider, stream, observed_at)
TTL toDateTime(observed_at) + INTERVAL 30 DAY;
