# data-contracts

Protobuf wire contracts for the Redpanda event bus (`MASTER_BUILD_SPEC.md` §18).

## Rules

1. **Exact decimals are strings.** Money, quantity and price fields are `string`, never `double`
   or `float`. Protobuf floating point loses precision silently, and an accounting record that
   disagrees with the venue is worse than none (`AGENTS.md` domain rule 6). Bounded scores that
   are never accounted for (confidence, sentiment) may use `double`.
2. **Timestamps are `google.protobuf.Timestamp`, always UTC.** Every message distinguishes
   `event_time`, `ingested_at` and `provider_revision_time` (§8.5).
3. **Field numbers are never reused.** `reserved` a removed number and its name.
4. **Only additive changes within a version.** A breaking change means a new `.v2` topic and
   message; consumers migrate deliberately.
5. **The envelope is mandatory.** Nothing is published bare.
6. **Tenant-scoped messages must set `TenantScope`.** Public market data must not.

## Files

| File | Topics |
|---|---|
| `envelope.proto` | envelope used by every topic |
| `market.proto` | `market.trade.raw.v1`, `market.book.raw.v1`, `market.candle.v1` |
| `decision.proto` | `agent.decision.v1`, `risk.evaluation.v1`, `order.intent.v1` |

Remaining topics from `MASTER_BUILD_SPEC.md` §18.2 (derivatives, on-chain, DeFi, tokenomics,
news, macro, security, features, portfolio, audit, billing) are defined as their producing
services are built.

## Generation

Generated Python lands in `_generated/` and is git-ignored; regenerate with `make proto`. The
`kavrigo_domain` Pydantic models are the in-process validation contract and must stay in step
with these definitions — a change to one requires a change to the other in the same pull request.
