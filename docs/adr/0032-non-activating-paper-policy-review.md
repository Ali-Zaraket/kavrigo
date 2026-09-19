# ADR 0032: Independent review before paper-policy evaluation

Status: accepted for the local control-plane slice, 2026-09-19.

## Context

ADR 0031 stores immutable policy candidates but cannot record a human review. The master
specification's promotion gates (§12.6) require evaluation and paper observation before any
later eligibility decision. A recommendation alone must not authorize order submission.

## Decision

Add one append-only `paper_policy_reviews` record per candidate bundle. A different workspace
admin or owner, with verified MFA and `risk_policy:write`, can recommend
`advance_to_evaluation` or `changes_requested` and must provide a reason. The review stores the
exact candidate risk and execution hashes. The caller must supply both expected hashes, so a
review cannot silently target a different candidate document. A retry with the same key, body and
reviewer returns the original record; conflicting reviews return 409. A transaction advisory
lock serializes concurrent reviews. The row and audit event commit together.

The recommendation is not an approval state. Candidate and review responses continue to state
`approval_status=unapproved` and `execution_enabled=false`. No order path consumes this review.
Any changed policy must be a new immutable candidate rather than a rewrite. Further evaluation,
paper observation, authorization and activation need separate gates and their own contracts.

## Security and operations

The database grants the application role SELECT and INSERT only. FORCE RLS scopes reviews to
the workspace; a composite foreign key prevents linking a review to a bundle in another
workspace. A trigger refuses update/delete. The API revalidates candidate hashes on read and
write, and checks reviewer separation. Structured logging records the recommendation without
the policy body; the audit event contains actor, reason, review ID and hashes.

Rollback removes the review table and its added bundle key after preserving any audit evidence
required by operators. It cannot grant execution capability, so existing paper runs are
unaffected.

Official PostgreSQL references checked 2026-09-19:
[row security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html) and
[transaction advisory locks](https://www.postgresql.org/docs/current/functions-admin.html).
