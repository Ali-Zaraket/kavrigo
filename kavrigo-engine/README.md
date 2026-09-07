# kavrigo-engine

Quant, data and agent services, plus the domain contracts every other repository depends on.

## Layout

```text
libs/domain/               Pydantic domain contracts — the shared vocabulary
libs/data-contracts/       Protobuf wire contracts for the Redpanda event bus
libs/market-data/          venue adapters, normalization, stream health, replay
services/market-ingestion/ pipeline, envelopes, ClickHouse sink
services/engine-worker/    worker skeleton; remaining services land here
tests/property/            Hypothesis invariants for money, risk and identity
```

## Market data

Venue message formats are transcribed from official documentation, with the source URL and
verification date recorded in each adapter module — nothing is written from recollection of a
venue API (`AGENTS.md` § Engineering workflow).

| Venue | Channels | Verified against |
|---|---|---|
| Binance spot | `@trade`, `@bookTicker`, `@kline_<interval>` | developers.binance.com, 2026-09-07 |
| Coinbase Exchange | `matches`, `ticker`, `heartbeat` | docs.cdp.coinbase.com, 2026-09-07 |

Three decisions worth knowing about:

- **Symbols are mapped, never inferred.** `BTCUSDT` cannot be split into base and quote without
  knowing the venue's quote assets, so adapters resolve symbols through an `InstrumentMap` built
  from what was actually subscribed. An unrecognised symbol is dropped, not guessed at.
- **The aggressor is derived, never passed through.** Binance's `m` means "was the *buyer* the
  maker"; Coinbase's `side` is the *maker's* side. Both are inverted to give the taker. Getting
  this wrong silently inverts CVD and every taker-imbalance feature (`MASTER_BUILD_SPEC.md` §7.2).
- **Unknown frames are skipped, not raised on.** Venues add message types without notice, and a
  parser that crashes on one turns a cosmetic upstream change into an ingestion outage.

Stream health (`StreamHealthMonitor`) tracks freshness, sequence gaps, duplicates, out-of-order
frames, parse failures and reconnects. It fails closed: a stream that has never produced a
message is `UNKNOWN`, not healthy, because a silent stream reporting healthy would let the risk
engine approve trades against data that does not exist.

A live production WebSocket transport is **not** wired in yet. Adapters, normalization, health
and sinks are complete and tested against recorded frames and a scripted transport; connecting a
real socket with keepalive is the next slice.

## Contracts

`libs/domain` encodes the non-negotiable domain rules structurally rather than by convention:

| Rule (`AGENTS.md`) | Where it lives |
|---|---|
| Money and quantity are exact decimals with units | `money.ExactDecimal`, `Money`, `Quantity`, `Price` |
| Instruments are explicit, never bare tickers | `identifiers.InstrumentId` |
| A model output is a proposal, never an order | `decision.AgentDecision`, `decision.ProposedAction` |
| Only deterministic risk produces an approval | `risk.RiskEvaluation`, `orders.ApprovedOrderIntent` |
| `UNKNOWN` and `NO_TRADE` are successful outcomes | `decision.DecisionState`, `ProposedAction` |
| Data freshness is a risk input | `snapshot.FreshnessReport`, `risk.FreshnessPolicy` |
| Every run references immutable versions | `agent.AgentVersion`, `audit.AuditRecord` |
| Untrusted content is data, not instruction | `evidence.EvidenceItem`, `events.SourceKind` |

Every model is frozen and rejects unknown fields, so an unvalidated provider payload or model
response cannot enter the domain unnoticed.

## Services not yet built

`market-ingestion`, `feature-engine`, `news-intelligence`, `agent-runtime`, `portfolio-engine`,
`risk-engine`, `backtest-service`, `paper-broker`, `reconciliation`
(`MASTER_BUILD_SPEC.md` §17). They are added in the order given by `AGENTS.md` § First build
sequence, each behind the contracts above.

Nothing in this repository holds an exchange credential or reaches a venue. Paper execution will
be simulated by the paper broker; live execution belongs to the separate
`kavrigo-execution-security` boundary.
