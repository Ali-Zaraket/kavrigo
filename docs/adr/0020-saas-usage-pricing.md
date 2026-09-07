# ADR 0020: SaaS subscription plus usage metering; no performance fee

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §34

## Context

AI inference and premium market data are real marginal costs, so a flat unmetered subscription has unbounded margin risk. Performance fees additionally create regulatory complexity and misaligned incentives.

## Options considered

1. **Flat subscription only** — simple, exposed to heavy-usage tenants.
2. **Subscription tiers plus metered usage for model cost, backtest compute and premium data packs.**
3. **Performance fee on trading results** — aligns marketing with returns, exactly the wrong incentive for this product.

## Decision

Option 2, using Stripe Billing with entitlements. Per-workspace and per-agent cost controls (max model cost per decision, max decisions per day, max tool calls, max backtest compute, max historical scan) are product features, not just billing (§46). No performance fees at launch.

## Security and compliance impact

Entitlement checks gate paid data packs, which is also how provider licence scope is enforced per tenant (§8.3). Billing entitlement code is a high-impact review path.

## Consequences

Easier: margin protection and honest incentives. Harder: usage metering must be accurate and explainable before it is billable.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
