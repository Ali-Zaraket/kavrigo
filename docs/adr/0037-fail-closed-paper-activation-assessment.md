# ADR 0037: Fail-closed paper-activation eligibility assessment

Status: accepted for the local control-plane slice, 2026-09-22.

## Context

ADR 0036 records approval of exact paper risk and execution policy documents, but approval alone
cannot activate an agent. The master specification also requires an immutable agent version,
completed evaluation evidence, an eligible data source, provider rights, operational readiness,
and explicit paper activation. Current rehearsals use synthetic inputs or Binance Spot Testnet;
neither is valid production-market evidence. No production data-provider entitlement has been
recorded.

The product needs a durable answer to “why can this version not run?” without changing its
version row, interpreting raw performance as approval, or creating an execution shortcut.

## Decision

Add an append-only `paper_activation_assessments` record bound to one workspace, immutable agent
version, approved policy bundle, approval, and evaluation run. The caller must repeat every
content hash. Readback revalidates a canonical hash over the ordered gate results.

The assessment records these independent gates:

1. approved policy integrity;
2. version-to-policy binding;
3. evaluation completion;
4. evaluation-to-version binding;
5. promotable evidence;
6. provider entitlement; and
7. activation support.

Synthetic evidence and testnet evidence fail the promotable-evidence gate. Development/testnet
providers fail provider entitlement, and all other providers remain blocked until a reviewed
entitlement record exists. Activation support is also explicitly blocked because the platform
does not yet implement an activation state or order-capable paper launch. Every current response
therefore says `decision=blocked`, `activation_status=inactive`, and
`execution_enabled=false`.

Assessment creation requires the MFA-gated `agent:promote` permission, a mandatory idempotency
key, and an operator reason. A transaction advisory lock serializes retries. The deterministic
assessment identity, request hash, actor, agent path, and version must all match before an
existing assessment can be returned.

## Security and operations

The table uses forced workspace row-level security, composite foreign keys, SELECT/INSERT-only
application privileges, and an append-only trigger. The policy, version, run definition, and
evaluation receipt are checked before a record is inserted. The assessment and its audit event
commit in one transaction. Structured logs report only the decision, failed-gate count, and
disabled execution state.

This slice adds no broker call, account state, order intent, exchange credential, provider data,
or live-trading path. A future activation workflow must replace the explicit support blocker
only after provider entitlement, licensed evidence, account readiness, supervision, and
reconciliation are implemented and tested.

Rollback removes the assessment table and its supporting composite unique constraints. It does
not activate, cancel, or mutate any agent, policy, run, account, or order.

Official PostgreSQL 18 references checked 2026-09-22:
[row security](https://www.postgresql.org/docs/18/ddl-rowsecurity.html),
[constraints](https://www.postgresql.org/docs/18/ddl-constraints.html), and
[advisory locks](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS).
