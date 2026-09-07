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
