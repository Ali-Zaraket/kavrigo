# ADR 0001: Paper-first launch with live execution behind a gate

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §5, §22, §23, §47

## Context

Real-money execution carries legal, licensing, custody, identity and operational obligations that vary by jurisdiction and are not yet answered (§64). Engineering readiness is not the binding constraint; legal classification, data rights and security assurance are. A platform that ships live execution before those gates cannot be un-shipped safely.

## Options considered

1. **Live from day one** — fastest perceived credibility, but exposes an unlicensed operator to execution/advice/portfolio-management classification and to custody-adjacent risk before counsel has reviewed it.
2. **Paper-first, live behind a hard flag** — full product value (research, backtest, evidence, risk) is demonstrable without touching a venue with user funds.
3. **Backtest-only** — safe but does not prove live-data behaviour, freshness handling, or continuous operation.

## Decision

Option 2. The repository ships with `LIVE_TRADING_ENABLED=false` and `DEFAULT_TRADING_MODE=paper`. Live execution is a separate, gated release requiring every item in §47. No code path may enable real-money execution implicitly, and paper and live must be visually unmistakable in the UI (§31).

## Security and compliance impact

Removes custody and unlicensed-execution exposure from V1. Requires that paper and live environments be separable enough to prevent credential or tool crossover (§36), and that marketing never presents simulated results as live results (§35).

## Consequences

Easier: legal review, security review, iteration speed. Harder: the product must earn trust through evidence and methodology rather than live P&L screenshots — which is the intended positioning.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
