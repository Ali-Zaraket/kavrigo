# ADR 0002: Non-custodial, spot-only scope for V1

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §15.1, §23

## Context

Custody and derivatives each add a distinct regulatory and risk surface. Holding user assets invites money-transmission and custody regimes; leveraged products add liquidation, funding and margin mechanics plus stricter consumer-protection rules.

## Options considered

1. **Custodial wallet** — better UX control, materially heavier licensing and security burden.
2. **Non-custodial exchange connection, spot only** — user keeps assets at a venue they already trust; platform needs trade/read scope only.
3. **Non-custodial with derivatives** — richer strategies, much larger risk-engine and disclosure surface.

## Decision

Option 2. The platform never holds user crypto, never requests withdrawal permission, and never accepts seed phrases or wallet private keys. Exchange credentials are trade/read scope, least privilege, IP-restricted where the venue supports it. Derivatives *data* is ingested for signal purposes; derivatives *execution* is out of scope for V1.

## Security and compliance impact

Reduces blast radius: a full compromise of the platform cannot move user funds off a venue. Withdrawal-disabled credential policy must be verified at connection time, not assumed.

## Consequences

Easier: security posture, licensing conversations. Harder: some strategies are unavailable, and the platform depends on venue API quality for reconciliation.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
