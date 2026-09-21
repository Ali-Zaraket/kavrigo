# ADR 0035: Binance Spot Testnet evidence for execution-disabled agent rehearsals

Status: accepted for local development, 2026-09-21.

## Context

The synthetic rehearsal proves workflow wiring but does not exercise a network market adapter.
Persisting or displaying mainnet exchange data remains blocked until Kavrigo has written rights.
Binance documents Spot Testnet as an API environment for practicing spot trading and provides a
public WebSocket stream with the same trade and book-ticker shapes as Spot. Its activity and
prices are simulated, so they cannot be represented as observations of the real BTC/ETH market.

## Decision

A local-only rehearsal may sample BTC/USDT and ETH/USDT from Binance Spot Testnet for at most 15
seconds. The adapter assigns the source venue `BINANCE_TESTNET`; it is never conflated with
`BINANCE`. The collector requires a book observation for every requested asset and fails closed
when the bounded sample is incomplete.

The durable agent input stores derived return/spread features and two evidence statements per
asset. It does not store raw WebSocket frames or claim that testnet activity describes current
market conditions. The saved AgentSpec remains the V1 USD/SIM paper instrument, while evidence
records its distinct Binance Testnet BTC/USDT origin. The run is labeled `testnet_rehearsal` in
the API and UI.

## Security and risk

No key, account stream or trading endpoint exists in this path. The rehearsal account retains a
global kill, zero exposure limits, unavailable connectivity, and zero allocation. The local mock
model can abstain only; the workflow cannot issue an order. `LIVE_TRADING_ENABLED=true` remains a
startup refusal. Testnet data is untrusted input and passes through the existing strict parser and
structured domain models before it can become evidence.

This is a functional agent/network rehearsal, not paper strategy activation, a backtest, a live
market signal or evidence of investment performance. Order-capable internal paper trading still
requires reviewed policy approval and a licensed real-market snapshot source.

Official source checked 2026-09-21:
[Binance Spot Testnet WebSocket streams](https://github.com/binance/binance-spot-api-docs/blob/master/testnet/web-socket-streams.md).

Rollback removes the testnet collector and source query. Existing immutable testnet rehearsals
remain correctly labeled and execution-disabled.
