# Data provider and licence matrix

**Status:** researched for development selection; no production licence is confirmed.

`MASTER_BUILD_SPEC.md` §8.3: *data licensing is a launch blocker.* The legal right to use and
display a provider's data is as much an engineering requirement as the API key. A public,
multi-tenant trading platform is a materially different use case from personal API consumption,
and provider terms distinguish **display** from **redistribution** in ways that decide product
design — not just legal paperwork.

Nothing may be shown to a user, stored beyond a permitted retention window, or exposed through
the API until the corresponding row is completed with written confirmation.

## Required per provider

| Field | Why it matters |
|---|---|
| Provider, plan, contract date | Establishes which terms apply |
| Commercial use permitted | Free/personal tiers routinely forbid commercial use |
| **Display** rights | Whether we may show the data to end users at all |
| **Redistribution** rights | Whether an API response of ours may contain their data |
| Derived-data rights | Whether features computed from it may be stored and shown |
| Raw storage and retention limit | Drives ClickHouse/S3 TTLs, which are currently placeholders |
| Attribution requirement | Exact wording and placement, enforced in the UI |
| Caching restrictions | Some terms cap cache duration |
| Rate limits and burst policy | Ingestion design and failover thresholds |
| Backtest/point-in-time snapshot rights | Whether §8.5 snapshots may be retained at all |
| Per-tenant entitlement requirement | Whether paid packs must be gated per workspace |
| Termination and data-deletion obligations | What must be purged, and how fast |

## Providers under consideration

| Provider | Intended use | Path | Licence status | Blocker |
|---|---|---|---|---|
| Binance spot market-data-only WS | local ephemeral trades/book ticker | native WS | **development only; production rights unconfirmed** | written commercial display, derived-data and retention rights |
| Binance Spot Testnet WS | local execution-disabled agent rehearsal | native WS | **simulated practice environment only** | never present as real-market data or performance evidence |
| Coinbase Exchange public WS | none | native WS adapter retained for tests only | **blocked** | Aug. 7, 2026 terms restrict third-party apps, external display/derived works, and AI/agent use without written consent |
| Kraken public API | none | not enabled | **blocked pending permission** | official API guide requires prior permission for non-personal commercial use |
| CoinGecko | reference universe, metadata and production price candidate | commercial API | **commercial contract required** | select a plan covering application display, derived data and retention; no raw API redistribution |
| CoinGlass | funding, OI, liquidations, positioning | REST (production), MCP (research) | **not confirmed** | commercial display rights; MCP is beta (ADR 0005) |
| Dune | custom on-chain queries, decoded contract data | API + MCP | **not confirmed** | derived-data and display rights |
| CryptoQuant | exchange-flow and on-chain metrics | REST | deferred | evaluate after V1 |
| Messari | token unlocks, vesting | REST | deferred | evaluate after V1 |
| DefiLlama | TVL, stablecoins, bridges | REST | deferred | evaluate after V1 |
| Glassnode | standardised on-chain metrics | REST | deferred | evaluate after V1 |
| Kaiko / CoinAPI | licensed normalised multi-venue data | REST | deferred | enterprise contract |

## Engineering consequences

1. **Data packs are entitlements, not feature flags.** A workspace may only enable a pack whose
   licence covers that tenant's use (`MASTER_BUILD_SPEC.md` §20, §46).
2. **Every event and evidence item carries a `license_ref`** (`EventSource.license_ref`,
   `EvidenceItem.license_ref`) so a retention or deletion obligation can be executed precisely.
   `VenueConfig.license_ref` is `None` for Binance today and the ingestion service logs
   `venue_license_unconfirmed` on startup — deliberately noisy, so this cannot be forgotten.
3. **Retention TTLs are licence-derived.** The values in the ClickHouse bootstrap are
   placeholders and must be replaced before any real ingestion.
4. **We do not proxy or resell raw provider APIs.** The API exposes our normalised, derived
   representation, subject to the derived-data rights above.
5. **Attribution is implemented in the UI**, not promised in a document.
6. **Point-in-time snapshot retention** (§8.5) may itself require a specific right. If a provider
   forbids storing historical responses, honest backtesting against that source is not possible
   and the limitation must be stated on the performance card rather than hidden.
7. **Activation reads immutable entitlement events.** Platform contract rights and per-workspace
   pack access are evaluated at both the evidence and assessment timestamps and bound into the
   activation receipt. The ledger is implemented but intentionally empty; see
   [provider entitlement operations](provider-entitlements.md) and ADR 0038.

## Before public launch

- [ ] Written confirmation of commercial display rights for every provider in use.
- [ ] Derived-data and retention rights documented per provider.
- [ ] Attribution implemented and verified in the UI.
- [x] Point-in-time per-tenant entitlement enforcement implemented for activation assessment.
- [ ] Compliance operator workflow and billing/plan synchronization implemented.
- [ ] Retention TTLs replaced with licence-derived values.
- [ ] A named owner for each provider relationship.

## Development selection — 2026-09-21

The local bounded sampler uses Binance's **market-data-only** WebSocket host for BTC/USDT and
ETH/USDT. Binance documents this endpoint for public market streams and documents its APIs as
interfaces for applications, services and trading systems. Its linked product terms do not state
the commercial display, derived-data, AI-agent and retention rights Kavrigo needs clearly enough
to approve production use. Consequently this source remains `license_ref=None`, is local-only,
is discarded after the bounded sample, and cannot feed the product UI or a persisted agent run.

Coinbase was removed from active configuration. Its current terms grant personal/research use
inside one entity and, absent written consent, prohibit building an application for other end
users, external display of market data or derived works, and using market data to operate an AI
agent. Keeping an adapter for deterministic parser tests does not access Coinbase data.

CoinGecko is the clearest production procurement path found: its official licensing page offers
commercial application-display and redistribution options. It is not enabled until a suitable
plan and written rights are recorded in this matrix.

Binance Spot Testnet is separately enabled for a local execution-disabled rehearsal. Its venue
identity is `BINANCE_TESTNET`, and every persisted evidence item says the source is simulated.
This path validates network parsing and the agent workflow; it is not a substitute for licensed
mainnet data and cannot support market or performance claims. See ADR 0035.

Sources reviewed:

- [Binance developer introduction](https://developers.binance.com/en/docs/introduction)
- [Binance spot market WebSocket streams](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md)
- [Binance spot product terms link](https://developers.binance.com/en/docs/products/spot/PROD-TERMS-OF-USE)
- [Coinbase Market Data Terms of Use](https://www.coinbase.com/legal/market_data)
- [Kraken API guide](https://docs-legacy.kraken.com/api/docs/guides/global-intro/)
- [CoinGecko commercial data licensing](https://www.coingecko.com/en/api/enterprise/data-license)
- [Binance Spot Testnet WebSocket streams](https://github.com/binance/binance-spot-api-docs/blob/master/testnet/web-socket-streams.md)
