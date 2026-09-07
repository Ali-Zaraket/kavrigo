# ADR 0011: Langfuse for LLM traces and evaluations

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §13.4, §26

## Context

Model behaviour needs prompt versioning, token/cost accounting, latency tracking and offline/online evaluation. Generic APM traces do not capture prompt/response structure or evaluation datasets.

## Options considered

1. **Generic OpenTelemetry traces only** — no prompt/eval semantics.
2. **Langfuse alongside OpenTelemetry.**
3. **Build an internal eval/trace store** — cost without differentiation at this stage.

## Decision

Option 2. Langfuse carries LLM traces, prompt versions, cost/latency metrics and evaluation datasets. OpenTelemetry remains the general observability spine. Langfuse is explicitly **not** the compliance source of truth: the immutable trade audit ledger (§25) is ours.

## Security and compliance impact

Prompt and response payloads may contain tenant data; retention and redaction policy must be configured per model profile before any real user data flows through it.

## Consequences

Easier: prompt iteration with measurement, golden eval datasets from the start. Harder: another data-processing vendor in the privacy review.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
