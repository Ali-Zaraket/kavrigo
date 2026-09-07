# Data provider and licence matrix

**Status:** template — not one row is confirmed.

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
| Exchange public WebSockets | trades, ticker, book, candles | native WS | **not confirmed** | venue terms per exchange |
| CoinGlass | funding, OI, liquidations, positioning | REST (production), MCP (research) | **not confirmed** | commercial display rights; MCP is beta (ADR 0005) |
| CoinGecko | reference universe, metadata, prices | commercial API | **not confirmed** | commercial tier; no redistribution of raw API access |
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
3. **Retention TTLs are licence-derived.** The values in the ClickHouse bootstrap are
   placeholders and must be replaced before any real ingestion.
4. **We do not proxy or resell raw provider APIs.** The API exposes our normalised, derived
   representation, subject to the derived-data rights above.
5. **Attribution is implemented in the UI**, not promised in a document.
6. **Point-in-time snapshot retention** (§8.5) may itself require a specific right. If a provider
   forbids storing historical responses, honest backtesting against that source is not possible
   and the limitation must be stated on the performance card rather than hidden.

## Before public launch

- [ ] Written confirmation of commercial display rights for every provider in use.
- [ ] Derived-data and retention rights documented per provider.
- [ ] Attribution implemented and verified in the UI.
- [ ] Per-tenant entitlement enforcement implemented for paid packs.
- [ ] Retention TTLs replaced with licence-derived values.
- [ ] A named owner for each provider relationship.
