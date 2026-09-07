# ADR 0014: Python and FastAPI for the application and quant backend

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §16.2

## Context

The backend spans API serving, quantitative computation, and AI orchestration. Splitting V1 across Node, Python and Go multiplies contract duplication and operational surface for no proven benefit.

## Options considered

1. **Node control plane + Python quant + Go execution** — right at large scale, three toolchains at day zero.
2. **Python throughout (FastAPI, Pydantic v2, asyncio), delegating hot paths to Rust/Arrow-backed libraries.**
3. **Go throughout** — excellent services, weak research ecosystem.

## Decision

Option 2. Python (current supported release) with FastAPI, Pydantic v2, uv for dependency and workspace management, Polars/PyArrow for analytical transforms, and NumPy/scikit-learn/gradient-boosting where justified. Performance-sensitive market simulation is delegated to NautilusTrader's Rust core. Rust or Go are added only after profiling demonstrates a bottleneck.

## Security and compliance impact

One validation layer (Pydantic) for domain contracts reduces the chance of an unvalidated model or provider payload entering the domain. All model JSON is schema-validated (§62.9).

## Consequences

Easier: one language for contracts, quant and AI. Harder: Python's performance ceiling on any future hot path we do not delegate.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
