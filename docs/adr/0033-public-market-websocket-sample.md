# ADR 0033: Public market WebSocket transport with ephemeral local sampling

Status: accepted for the local ingestion slice, 2026-09-19.

## Context

Venue parsers, stream health, and ClickHouse sinks existed, but the ingestion entry point had
no real socket. The approval pipeline cannot treat synthetic rehearsal data as a real market
evaluation. Provider commercial display, derived-data, snapshot and retention rights remain
unconfirmed in `docs/product/data-license-matrix.md`; ClickHouse TTLs are still placeholders.

## Decision

Add `PublicWebSocketTransport` behind the existing `Transport` protocol. It accepts a configured
public WSS endpoint without credentials, limits frame size and queued frames, decodes JSON
objects, and turns connection closures into recoverable transport events. The WebSocket library
handles protocol Ping/Pong and sends keepalive pings. `IngestionPipeline` owns reconnect backoff,
parser validation, sequence-gap tracking and sink flushes. Local loopback WS is allowed only
with an explicit test override.

The entry point remains configuration-only by default. With `KAVRIGO_ENV=local` and
`KAVRIGO_INGESTION_SAMPLE_SECONDS=1..60`, it connects to the configured public BTC/ETH feeds
for a bounded interval. A `CountingSink` discards normalized events; logs contain counts and
health-related errors but no prices or raw frames. It does not write ClickHouse, Redpanda, a
file, the API or the UI. It does not change any approval or paper execution state.

## Security and operations

No exchange credential or order endpoint is used. The transport rejects URL credentials, query strings and
insecure non-loopback connections. Socket sizes and durations are bounded. A malformed or
non-object JSON message becomes a skipped frame rather than terminating ingestion. The parser
still rejects unknown or unmapped instruments. Reconnection and duplicate handling are tested
against a local WebSocket server; no external provider is required for tests.

This slice enables transport verification, not licensed collection or product display. Durable
real-data ingestion requires confirmed rights, licence-derived retention, and a separate
operational rollout. Rollback removes the transport and sample option; no stored provider data
needs migration.

Official sources checked 2026-09-19:
[Binance Spot WebSocket streams](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md),
[Coinbase Exchange WebSocket overview](https://docs.cdp.coinbase.com/exchange/websocket-feed/overview),
[Coinbase channels](https://docs.cdp.coinbase.com/exchange/websocket-feed/channels), and
[websockets asyncio client](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html).

Superseded in part by ADR 0034: the active sample now uses only Binance's market-data-only host;
Coinbase was removed after a current terms review.
