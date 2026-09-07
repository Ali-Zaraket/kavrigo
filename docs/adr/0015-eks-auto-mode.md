# ADR 0015: AWS EKS Auto Mode for application compute

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §16.11

## Context

The workload mix is long-running market stream consumers, background workers, and request-serving APIs. Long-lived stateful connections fit poorly with function-style serverless.

## Options considered

1. **EKS Auto Mode** — Kubernetes ecosystem with managed compute, networking and storage.
2. **ECS Fargate** — simpler, less flexible for varied compute and the Kubernetes tooling we want.
3. **Lambda-first serverless** — wrong shape for persistent WebSocket consumers.

## Decision

Option 1. Application compute runs on EKS Auto Mode. Stateful managed databases stay outside the cluster. The execution deployment is a separate, network- and IAM-isolated boundary (§15.2).

## Security and compliance impact

Pod-level IAM identity, network policies, private subnets and no public database endpoints. The execution gateway's IAM role must be assumable only by the isolated execution deployment.

## Consequences

Easier: long-running consumers, varied workload shapes. Harder: Kubernetes remains an operational competency to maintain.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
