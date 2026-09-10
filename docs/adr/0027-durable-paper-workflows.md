# ADR 0027: PostgreSQL paper authority and Temporal run orchestration

- Status: Accepted for local durable integration; independent review pending
- Date: 2026-09-09
- Requirements: AGENTS step 13; MASTER_BUILD_SPEC §§15.4–15.5, 19, 20, 37; ADRs 0009, 0025–0026

## Decision and alternatives

Step 12 keeps receipts in memory. Temporal retries alone cannot recover lost account state or
prevent duplicate fills. Choose PostgreSQL as paper authority, with a deterministic command
journal and transactional receipts/outbox. Reject serializing Python objects or trusting an
imported replay bundle as execution permission. Keep Temporal as the outer run coordinator;
no market tick is a workflow event. A separate workflow package owns these adapters.

Each account command locks its tenant-scoped row. A monotonically increasing database lease
token fences worker writes; validity uses database time and is checked again before commit.
Committed idempotency lookups remain readable after lease expiry. Replay reconstructs domain
risk and paper state from immutable commands at their recorded times, then checks the state
hash. Risk evaluation, permit issuance, simulated submission and the receipt commit together.
There is no external venue side effect inside the transaction.

New generations require all orders terminal and a reconciled fresh ledger. Carry exact cost
basis, cash, fees, marks and P&L into the next generation; never reseed from rounded averages.
Prior receipts remain immutable and deduplicate across generations. Scope and expected
generation checks prevent stale proposals from using newly freed resources. Keep explicit
command/byte limits; exceeding them fails closed rather than deleting history.

Temporal inputs/results carry tenant/run references and hashes. Frozen financial/evidence
artifacts live in PostgreSQL. Activities use durable stage receipts. A model dispatch whose
outcome is unknown after a crash is not automatically repeated; the run stops without trading.
Deterministic database and historical backtest operations can retry with the same keys.
Register evaluation, backtest, data-health and paper-supervision workflows with bounded retry
and activity timeouts. Replayed workflow history must never run domain or provider code.

## Operations, security and rollback

Use forced RLS, parameterized SQL, append-only command/receipt records and a transactional
outbox. The local worker is trusted service code, not an authenticated tenant API. Cloud
namespace auth, hosted exporters, production identity/authorization and independent review
remain launch work. No exchange credentials or execution-security implementation is added.
The local Temporal dev server gains a named persistent store for restart tests; Temporal Cloud
remains the deployment target. The current Nautilus adapter still lacks strategy/data wiring;
workflow completion must not promote a zero-decision result into a meaningful backtest.

Rollback stops workers before reverting code/schema. Retain account journal and Temporal
history; destructive down-migration is only for isolated test databases or verified backup.
Do not revert a durable account to the step 12 in-memory consumer after receipts exist.

## Official sources checked

Checked 2026-09-09: [Temporal Python SDK](https://github.com/temporalio/sdk-python),
[Pydantic converter](https://python.temporal.io/temporalio.contrib.pydantic.html),
[workflow replay](https://python.temporal.io/temporalio.worker.Replayer.html),
[error handling](https://docs.temporal.io/develop/python/best-practices/error-handling),
[PostgreSQL locking](https://www.postgresql.org/docs/current/explicit-locking.html).
PyPI reports Temporal SDK 1.32.0; pin that release. Installed Temporal CLI help confirms
`server start-dev --db-filename` persists workflow executions across server starts.

Daily P&L requires an explicit future rollover design. This slice refuses new orders, matching
and generation advance across the account's initial UTC day, while permitting cancellation and
reconciliation. Continuous multi-day operation cannot be enabled by resetting a risk session.
