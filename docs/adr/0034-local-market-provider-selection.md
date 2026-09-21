# ADR 0034: Binance market-data-only stream for local ephemeral development

Status: accepted for local development, 2026-09-21.

## Context

The public WebSocket transport initially configured Binance and Coinbase. A current terms review
found that Coinbase expressly restricts third-party application, external derived-work display,
and AI-agent use without written consent. Binance documents a dedicated public market-data-only
host, but Kavrigo does not yet have written commercial display, derived-data or retention rights.
The first usable paper path needs real BTC/ETH observations without creating a credential or
execution path and without silently treating development access as a production licence.

## Options

1. Keep both exchange feeds. Rejected because Coinbase's current terms are incompatible.
2. Use Binance's market-data-only host for bounded local validation. Selected for development.
3. Buy a normalised-data contract now. Deferred until product requirements and entitlement scope
   are stable; CoinGecko is the clearest published commercial licensing path found.
4. Use Spot Testnet prices. Rejected for agent evaluation because testnet market activity and
   prices are simulated and cannot support claims about current market conditions.

## Decision

The default local feed contains BTC/USDT and ETH/USDT from
`wss://data-stream.binance.vision/ws`. It has no credentials, account stream or order capability.
Coinbase remains available only as a parser exercised by recorded unit-test fixtures. The local
sampler remains explicit, bounded to 1–60 seconds, count-only and non-persistent.

The agent rehearsal remains synthetic and execution-disabled. Real provider observations do not
enter a persisted agent snapshot or the UI until a contract confirms the required use. Internal
paper execution will consume a frozen licensed snapshot in a later vertical slice; it will never
send an order to Binance.

## Security, compliance and operations

`LIVE_TRADING_ENABLED=true` is still refused. The selected host cannot carry user-data streams,
and no API key is accepted. Provider data is discarded rather than written to PostgreSQL,
ClickHouse, logs or the browser. Production configuration must fail closed while `license_ref` is
unset. Loss of the socket is handled by bounded reconnect logic and does not change risk state.

Rollback restores the prior endpoint/configuration; there is no provider data to migrate or
delete. Production adoption requires a separate decision recording contract scope, attribution,
retention, entitlements and termination deletion obligations.
