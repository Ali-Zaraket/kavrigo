# ADR 0018: Declarative AgentSpec; no arbitrary user code in V1

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §9, §9.1

## Context

Executing user-authored code inside core services would put untrusted code next to market data, model budgets, tenant state and — eventually — execution paths. It is also unnecessary for the initial product thesis.

## Options considered

1. **Arbitrary user Python in core services** — maximum flexibility, unacceptable isolation risk.
2. **A declarative, inspectable `AgentSpec`, produced by natural language, structured controls, or templates.**
3. **No user configuration at all** — safe and uninteresting.

## Decision

Option 2. Natural language compiles into an `AgentSpec` that the user reviews before activation; the structured spec is authoritative, not the conversation. A sandboxed 'Code Strategy' tier may come later with strong isolation, no production credentials, an outbound network allowlist, CPU/RAM/time quotas, read-only point-in-time datasets, signed artifacts and lockfiles — and it will not be part of the first live-trading launch.

## Security and compliance impact

Removes remote code execution from the V1 threat model. The natural-language compiler itself must treat its input as untrusted and validate the resulting spec against the schema before persistence.

## Consequences

Easier: isolation, reproducibility, comprehensible agent diffs. Harder: expressiveness is bounded by the DSL, so the spec schema must evolve deliberately and versioned.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
