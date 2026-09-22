# ADR 0036: Immutable approval of reviewed paper policies

Status: accepted for the local control-plane slice, 2026-09-21.

## Context

ADR 0032 records a second-person recommendation but deliberately stops before approval. A
reviewed candidate needs an explicit approval record before a later activation workflow can
consider it. Approval must identify the exact immutable risk and execution documents, preserve
two-person control, and remain incapable of submitting an order by itself.

## Decision

Add one append-only `paper_policy_approvals` record per candidate bundle. Only the reviewer who
recorded `advance_to_evaluation` may approve that review, using a session with verified MFA and
`risk_policy:write`. The candidate creator remains unable to review or approve their own
candidate. The request must repeat the review ID and both candidate hashes. Any mismatch, a
`changes_requested` recommendation, or a different approver fails closed.

The approval ID is deterministic for the bundle. A transaction advisory lock serializes
concurrent requests, while the unique constraints provide a database guard. Same-key, same-body
retries return the stored approval; conflicting retries return 409. Bundle and review reads now
show `unapproved`, `reviewed`, `changes_requested`, or `approved` from their append-only records.

Approval remains non-activating: every approval response says `activation_status=inactive` and
`execution_enabled=false`. No runtime, broker, or order path consumes this record. Activation
will need a separate contract that also proves data-provider eligibility, evaluation evidence,
account readiness, and operational gates.

## Security and operations

The approval table uses forced workspace row-level security, composite foreign keys to its
review and bundle, and SELECT/INSERT-only application privileges. An append-only trigger refuses
updates and deletes. Readback revalidates the reviewer, recommendation, workspace, review ID, and
both hashes. The approval and audit event commit in one transaction. Structured logs contain the
inactive state but no policy document or tenant identifier.

Rollback removes the approval table and the supporting review composite key after preserving
audit evidence required by operators. It does not alter any paper account or execution state.

Official PostgreSQL 18 references checked 2026-09-21:
[row security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html),
[constraints](https://www.postgresql.org/docs/18/ddl-constraints.html), and
[advisory locks](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS).
