# ADR 0007: Aurora PostgreSQL for the control plane

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §16.6, §20

## Context

Users, workspaces, agent versions, policies, entitlements, approvals and current order/position projections need transactions, constraints, and a strong row-level tenancy story.

## Options considered

1. **Aurora PostgreSQL** — managed, mature transactions, native RLS, PITR.
2. **Self-managed PostgreSQL on EKS** — cheaper, materially more operational risk for authoritative state.
3. **A document store** — weaker constraints and transactional guarantees for financial control state.

## Decision

Option 1. Aurora PostgreSQL holds authoritative control-plane state. PostgreSQL RLS is used as defence-in-depth for tenant-scoped tables, in addition to (never instead of) backend authorization. Stateful managed databases stay outside the Kubernetes cluster.

## Security and compliance impact

RLS is a second line of defence against a query that forgets a tenant predicate. Every service request must carry a verified workspace context; frontend filtering is never a boundary.

## Consequences

Easier: correctness of authoritative state. Harder: schema migrations become high-impact changes requiring stricter review.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
