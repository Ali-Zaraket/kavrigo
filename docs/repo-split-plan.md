# Repository split plan

`MASTER_BUILD_SPEC.md` §17 and ADR [0019](adr/0019-hybrid-repository-structure.md) define five
repositories. The GitHub organization does not exist yet, so they are mirrored here as top-level
directories. This document is the contract for how that temporary arrangement ends.

## Target repositories

| Directory | Target repository | Visibility | Reviewers |
|---|---|---|---|
| `kavrigo-platform/` | `kavrigo-platform` | private | `@kavrigo/engineering` |
| `kavrigo-engine/` | `kavrigo-engine` | private | `@kavrigo/engineering`, risk paths `@kavrigo/risk` |
| `kavrigo-execution-security/` | `kavrigo-execution-security` | **restricted private** | `@kavrigo/execution-security` only |
| `kavrigo-infra/` | `kavrigo-infra` | private | `@kavrigo/platform` |
| `kavrigo-research/` | `kavrigo-research` | private | `@kavrigo/research` |

## Rules that hold during the bootstrap phase

1. **The execution-security boundary is not blurred.** `kavrigo-execution-security/` contains no
   code, no credentials, and no venue adapters while it lives in a shared repository. Execution
   work starts only after the restricted repository exists.
2. **No cross-directory imports** except through published contracts. `kavrigo-platform` may
   depend on `kavrigo-engine/libs/domain` and on generated Protobuf; nothing depends on
   `kavrigo-research`.
3. **Contracts are the only shared surface.** `kavrigo-engine/libs/domain` (Pydantic) and
   `kavrigo-engine/libs/data-contracts` (Protobuf) are treated as if they were already a
   published, versioned package.
4. **No production credentials anywhere in this repository**, including CI.

## Split procedure

When the organization exists:

1. Create the five repositories with branch protection, `CODEOWNERS`, secret scanning, CodeQL
   and Dependabot enabled before any code is pushed.
2. Split with history preserved (`git subtree split` or `git filter-repo` per directory).
3. Publish `kavrigo-engine/libs/domain` and the generated Protobuf as versioned internal
   packages; switch `kavrigo-platform` from a path dependency to a version constraint.
4. Move CI from the single root workflow to per-repository workflows sharing reusable actions.
5. Create `kavrigo-execution-security` last, with the most restrictive access, and only then
   begin execution-gateway work.
6. Archive the bootstrap repository read-only; do not keep dual sources of truth.

## Exit criteria

- Each repository builds and tests independently in CI.
- `kavrigo-platform` consumes the domain contracts as a versioned dependency, not a path.
- No AI coding tool, CI job, or developer outside `@kavrigo/execution-security` has access to
  the execution repository or its secrets.
