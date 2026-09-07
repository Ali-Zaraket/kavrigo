# kavrigo-engine

Quant, data and agent services, plus the domain contracts every other repository depends on.

## Layout

```text
libs/domain/               Pydantic domain contracts — the shared vocabulary
libs/data-contracts/       Protobuf wire contracts for the Redpanda event bus
libs/market-data/          venue adapters, normalization, stream health, replay
libs/signals/              deterministic, versioned, point-in-time feature engine
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

## Feature engine

Thirteen features across six families, covering what `AGENTS.md` step 6 requires — returns,
volume, volatility, spread, order-book imbalance, relative strength — plus VWAP and the
order-flow pair from `MASTER_BUILD_SPEC.md` §7.1/§7.2.

| Family | Features |
|---|---|
| price | `return_5m`, `return_15m`, `return_1h`, `vwap_15m` |
| volume | `volume_15m`, `volume_zscore_1h` |
| volatility | `realized_volatility_15m`, `realized_volatility_1h` |
| microstructure | `spread_bps`, `book_imbalance` |
| order_flow | `cvd_15m`, `taker_buy_ratio_15m` |
| relative_strength | `relative_strength_1h` |

Three properties hold, each enforced rather than intended:

- **Point-in-time.** A window contains only events whose `received_at <= as_of`. Knowability is
  arrival, not venue time — filtering on venue time would erase the latency a live system
  actually suffers and leak the future into every decision. A property test asserts that no
  event arriving after `as_of` can change any feature value.
- **Deterministic.** Decimal arithmetic in a fixed context, so no other library's context change
  can alter a recorded value, and window sorting is a *total* order — sorting on timestamps
  alone left simultaneous events in input order, which made a replay disagree with the original
  run. Fixed precision is deterministic, not exact: irrational intermediates leave a ~1e-28
  residue that is identical on every machine.
- **Versioned.** Every feature carries a version and the set carries a pinned manifest hash,
  because a formula change means a new agent version (`MASTER_BUILD_SPEC.md` §38).

A feature that cannot be computed reports `None` with a reason and is never defaulted to zero.
A one-hour return over four minutes of data is a different quantity, not a small error — and
downstream, a stated absence drives abstention while a fabricated zero drives a trade.

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
