# Architecture Decision Records

An ADR records a decision, its context, the options rejected, and the evidence — so that a
future reader can tell whether the decision is still valid. Use `0000-template.md`.

Rules (`AGENTS.md` § Architecture-change rule):

1. Do not silently deviate from `MASTER_BUILD_SPEC.md`.
2. Research current official sources before proposing a change.
3. Write the ADR (context, options, evidence, security/compliance impact, operational impact,
   migration/rollback), decide, then implement.
4. Supersede an ADR with a new one; do not rewrite an accepted decision in place.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-paper-first-live-gated.md) | Paper-first launch, live execution behind a gate | Accepted |
| [0002](0002-non-custodial-spot-first.md) | Non-custodial, spot-only scope for V1 | Accepted |
| [0003](0003-hierarchical-agent-topology.md) | Hierarchical scanner / network / asset / portfolio topology | Accepted |
| [0004](0004-deterministic-risk-outside-llm.md) | Deterministic risk engine outside the model | Accepted |
| [0005](0005-mcp-research-rest-production.md) | MCP for research; REST/WebSocket for production data | Accepted |
| [0006](0006-redpanda-streaming.md) | Redpanda as the event bus | Accepted |
| [0007](0007-aurora-postgres-oltp.md) | Aurora PostgreSQL for the control plane | Accepted |
| [0008](0008-clickhouse-analytics.md) | ClickHouse for analytical and time-series data | Accepted |
| [0009](0009-temporal-workflows.md) | Temporal Cloud for durable workflows | Accepted |
| [0010](0010-agents-sdk-model-gateway.md) | Agents SDK behind an internal `ModelGateway` | Accepted |
| [0011](0011-langfuse-llm-observability.md) | Langfuse for LLM traces and evaluations | Accepted |
| [0012](0012-nautilustrader-engine.md) | NautilusTrader (stable) behind internal adapters | Accepted |
| [0013](0013-nextjs-shadcn-baseui.md) | Next.js with shadcn/ui on Base UI | Accepted |
| [0014](0014-python-fastapi-backend.md) | Python and FastAPI for backend and quant | Accepted |
| [0015](0015-eks-auto-mode.md) | AWS EKS Auto Mode for application compute | Accepted |
| [0016](0016-opentofu-argocd.md) | OpenTofu for infrastructure, Argo CD for delivery | Accepted |
| [0017](0017-kms-isolated-credential-service.md) | KMS envelope encryption, isolated credential service | Accepted |
| [0018](0018-declarative-agentspec-no-user-code.md) | Declarative `AgentSpec`; no arbitrary user code in V1 | Accepted |
| [0019](0019-hybrid-repository-structure.md) | Hybrid repository structure | Accepted |
| [0020](0020-saas-usage-pricing.md) | SaaS plus usage metering; no performance fee | Accepted |
| [0021](0021-standards-based-token-verification.md) | Standards-based token verification behind an identity abstraction | Accepted |
| [0022](0022-local-model-gateway-reservations.md) | Local model gateway reservations and recorded replay | Accepted |
| [0023](0023-local-news-evidence.md) | Local news extraction with service-owned provenance | Accepted |
