# ADR 0019: Hybrid repository structure

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §17

## Context

A repository per microservice multiplies CI duplication, contract drift and dependency fragmentation. A single monolith blurs the execution-security boundary that ADR 0017 depends on.

## Options considered

1. **One repository for everything** — simplest, defeats the credential isolation boundary.
2. **A repository per service** — maximum isolation, heavy overhead at this team size.
3. **Five repositories split at real security, team and lifecycle boundaries.**

## Decision

Option 3: `kavrigo-platform`, `kavrigo-engine`, `kavrigo-execution-security`, `kavrigo-infra`, `kavrigo-research`. While the GitHub organization does not yet exist, these are mirrored as top-level directories in a bootstrap repository, with the split plan recorded in `docs/repo-split-plan.md`. The execution-security boundary stays empty of code until it is a separate access-restricted repository.

## Security and compliance impact

The repository boundary is part of the access-control model: `kavrigo-execution-security` is restricted to a small set of maintainers, and `kavrigo-research` never holds production credentials. Splitting at security boundaries is the point, not an aesthetic preference.

## Consequences

Easier: shared contracts within a repo, restricted review where it matters. Harder: cross-repo contract versioning once the split happens — which is why contracts are generated and versioned artifacts.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
