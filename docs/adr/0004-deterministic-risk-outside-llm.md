# ADR 0004: Deterministic risk engine outside the model

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §6.6, §11

## Context

A language model can be persuaded — by crafted news content, tool output, or its own error — to justify an oversized or prohibited position. Risk limits that live inside a prompt are advisory, not enforceable.

## Options considered

1. **Risk rules in the prompt** — flexible, trivially bypassable, unauditable.
2. **LLM-based risk reviewer agent** — sounds thorough, still probabilistic, still promptable.
3. **Deterministic versioned policy code the model cannot address**.

## Decision

Option 3. The model may only propose an action (`BUY`/`SELL`/`REDUCE`/`CLOSE`/`HOLD`/`NO_TRADE`). A deterministic risk engine, executing a versioned `RiskPolicy`, decides whether an `OrderIntent` is permitted and at what maximum size, and emits machine-readable reason codes. No prompt, tool, or model output can modify risk policy at runtime. `UNKNOWN` and `NO_TRADE` are successful outcomes. Data freshness is a risk input: stale, unknown or unreconciled state rejects.

## Security and compliance impact

This is the platform's primary containment boundary against prompt injection and excessive agency (OWASP LLM Top 10). It must be covered by property tests proving that a rejected intent can never produce an order command and that limits cannot be exceeded.

## Consequences

Easier: reasoning about worst-case behaviour, auditing, incident response. Harder: the model cannot express strategies that require breaking a limit — which is the point.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
