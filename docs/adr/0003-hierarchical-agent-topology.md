# ADR 0003: Hierarchical scanner / network / asset / portfolio topology

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §6

## Context

Running an independent, continuously-reasoning LLM per token is expensive, produces uncorrelated per-asset opinions that hide portfolio-level crowding, and repeatedly rediscovers the same chain-wide facts.

## Options considered

1. **One LLM per asset, always on** — simple, unboundedly expensive, blind to correlation.
2. **Single monolithic prompt over the whole universe** — cheap, but context-limited and unable to go deep.
3. **Funnel: deterministic scanner → shared network/sector context → selective asset analysis → portfolio layer → deterministic risk**.

## Decision

Option 3. The scanner is statistical, not LLM-driven. Network/sector context is computed once and shared. Expensive reasoning runs only on candidates that a cheap deterministic prefilter justified. The portfolio layer evaluates correlation, concentration and competing opportunities before risk evaluation.

## Security and compliance impact

Cost governance is a security-adjacent control (§46): an ungoverned agent loop is a denial-of-wallet vector. Per-workspace and per-agent model budgets are mandatory.

## Consequences

Easier: cost control, correlation awareness, shared context. Harder: more moving parts and more inter-stage contracts to version.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
