# ADR 0005: MCP for agent research; REST/WebSocket for the production data path

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §8.1

## Context

Market data ingestion is high-throughput and latency-sensitive. MCP is a tool-calling protocol designed for agent interaction, and at least one provider (CoinGlass) both labels its MCP service as beta and recommends REST for backend/high-performance production use.

## Options considered

1. **MCP as the primary feed** — one integration style, but wrong throughput/latency profile and beta schema risk on a critical path.
2. **REST/WebSocket for production ingestion, MCP for research and analyst tooling.**
3. **REST/WebSocket only** — forgoes a genuinely useful exploratory interface.

## Decision

Option 2. The production path is provider stream/REST → normalizer → event stream → feature engine/storage → frozen snapshot → agent. MCP is used for exploratory analysis, research and internal tooling, and its output is treated as untrusted content subject to the same sanitization pipeline as news (§14).

## Security and compliance impact

MCP servers are a supply-chain and tool-poisoning surface. No MCP connection may carry exchange write credentials, withdrawal capability, production KMS decrypt, or unrestricted production database access (§56).

## Consequences

Easier: predictable ingestion performance and schema stability. Harder: two integration styles per provider where both are used.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
