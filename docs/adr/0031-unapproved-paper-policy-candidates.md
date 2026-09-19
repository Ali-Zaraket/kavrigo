# ADR 0031: Immutable paper-policy candidates before approval

Status: accepted for the local control-plane slice, 2026-09-19.

## Context

The Studio draft form can hold policy references, but no workspace-scoped policy record existed.
An arbitrary well-formed ID was therefore not evidence of a reviewed limit or execution model.
MASTER_BUILD_SPEC §§11 and 38 require versioned deterministic risk and governed promotion.
The existing permission matrix also requires verified MFA for `risk_policy:write`.

## Decision

Add an append-only `paper_policy_bundles` record pairing one version-1 agent-scope risk policy
with one versioned USD-spot paper execution assumption set. A bundle gets server-derived IDs,
canonical hashes, a creation reason and an audit record in the same transaction. The POST is
workspace-scoped and requires `risk_policy:write`, including verified MFA. GET and list require
`risk_policy:read`. A mandatory idempotency key determines the bundle ID; a transaction advisory
lock serializes concurrent same-key requests, and the stored request hash rejects changed input.

Every response says `unapproved` and `execution_enabled=false`. No approval, activation,
order, or policy relaxation endpoint is added. A later approval lifecycle must evaluate these
records alongside agent-version, provider and operational gates. A new candidate receives new
immutable IDs; an agent that adopts it must create a new `AgentVersion`.

## Security and operations

PostgreSQL grants the application role only SELECT and INSERT. FORCE RLS and an append-only
trigger protect the tenant boundary and historical configuration. The API validates decimal
strings without binary floats and requires explicit age limits for each required data family.
Readback verifies both document hashes before returning values. Structured logs record the
creation event without policy bodies or tenant IDs; the audit row records actor, reason and
hashes. Existing synthetic rehearsals remain globally stopped even if a draft references a
candidate. The local browser's development identity does not claim MFA, so policy writes must
use a genuinely MFA-verified API session or a clearly isolated test identity.

Rollback removes the route and table after preserving/exporting any candidate records needed
for audit. There is no authoritative execution state to migrate.

Official PostgreSQL references checked 2026-09-19:
[row security](https://www.postgresql.org/docs/17/ddl-rowsecurity.html) and
[transaction advisory locks](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS).
