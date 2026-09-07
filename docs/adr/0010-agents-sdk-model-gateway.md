# ADR 0010: OpenAI Agents SDK behind an internal ModelGateway

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §13.2, §13.5

## Context

The AI layer needs tool orchestration and structured output today, without binding the domain to one vendor, and without a provider fallback silently changing the model that produced a reproducible result.

## Options considered

1. **Direct provider SDK calls throughout the domain** — fastest, creates vendor lock-in at every call site.
2. **Agents SDK for tool execution, behind an internal `ModelGateway` protocol, with a gateway (e.g. Portkey) for routing/budgets/fallback.**
3. **LangGraph as the primary orchestrator** — see ADR 0009: Temporal already owns durable process state; two co-equal orchestrators duplicate semantics.

## Decision

Option 2. No domain component depends directly on a model vendor. Model selection is expressed as routing *profiles* (`extract_fast`, `classify_fast`, `reason_balanced`, `reason_deep`, `embed`) rather than hard-coded model names. Backtests pin a resolved model identifier or a recorded response artifact; a fallback may never silently alter a reproducible run.

## Security and compliance impact

The gateway enforces per-workspace spend policy, rate limits and guardrails, and is the choke point for ensuring no credential or secret ever enters model context. All model output is schema-validated before use.

## Consequences

Easier: provider substitution, cost governance, reproducibility. Harder: an extra abstraction layer between the code and the provider's newest features.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
