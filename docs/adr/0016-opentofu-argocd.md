# ADR 0016: OpenTofu for infrastructure, Argo CD for deployment

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §16.13, §16.14

## Context

Infrastructure and deployment must be reviewable by specialists, auditable after the fact, and free of long-lived cloud credentials in CI.

## Options considered

1. **OpenTofu (HCL) + Argo CD pull-based GitOps.**
2. **Pulumi** — infrastructure in a general-purpose language; couples infra review to application-language expertise.
3. **CI running `kubectl apply`** — fast, no durable desired-state record, and pushes cluster credentials into CI.

## Decision

Option 1. OpenTofu with reusable modules, remote encrypted state, separate state per environment, plan review in the pull request, and no developer local apply to production. GitHub Actions builds, tests, scans, signs and pushes to ECR; Argo CD pulls desired state into EKS. GitHub OIDC to AWS means no long-lived CI cloud keys.

## Security and compliance impact

Removes standing cloud credentials from CI. Desired state is a reviewable, revertible artifact — which matters for post-incident reconstruction. Live-environment deploys of execution-sensitive components require a manual review gate.

## Consequences

Easier: audit and rollback. Harder: two systems (infra and app delivery) with distinct promotion mechanics.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
