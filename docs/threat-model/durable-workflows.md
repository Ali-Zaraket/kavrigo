# Durable workflow threat review

Author review for ADR 0027, 2026-09-10. Independent security/CODEOWNERS review is pending.

| Failure or threat | Enforcement and evidence | Residual limit |
|---|---|---|
| Duplicate command or lost commit acknowledgement | Unique workspace/account/key, immutable receipt returned before lease checks; concurrent and acknowledgement-loss tests | Caller must retain its original key |
| Crash between risk issuance and simulated submission | Risk, journal, account state, stage receipt and outbox commit in one PostgreSQL transaction; rollback fault test | Applies to the internal simulator, never an external venue |
| Split-brain writers | Account row lock, monotonic DB lease token, database-clock expiry recheck before commit; replacement/expiry tests | Trusted service config; no hosted deployment or live venue fencing |
| Cross-tenant read/write | Workspace query predicates and forced RLS under non-owner role; all engine tables tested | Worker/Temporal callers are trusted local services, not a user-facing auth layer |
| Forged or rewritten financial history | Append-only commands, input/result protection triggers, exact deterministic replay and state-hash checks | Hashes are integrity checks, not authentication against a database administrator |
| Reusing risk capacity | New generation requires terminal orders and fresh reconciled portfolio; exact basis carried, historical decision IDs retained | Bounded account journal; no compaction or automatic generation controller |
| Unknown model dispatch after crash | Persist dispatch before call; subsequent attempt records uncertain and never calls provider again; late result cannot rewrite receipt | No paid provider or shared billing ledger |
| Workflow replay repeats side effects | Workflow history contains references only; I/O in activities; durable stage receipts; actual SDK Replayer tests | Future workflow changes require history compatibility review |
| Frozen evidence leaks to orchestration logs/history | Pydantic references/statuses only, closed activity errors, metadata logs, inspection of decoded history payloads | Hosted exporters, encryption and retention policies remain unconfigured |
| Stale/conflicting market data | Health checks emit refused status/outbox; independent risk freshness checks and paper reconciliation gate execution | Health workflow does not connect to a provider or automatically page operators |
| Misleading backtest success | Zero-decision Nautilus result retained but workflow refused | Meaningful strategy/data/benchmark implementation still pending |
| Test cleanup erases durable accounts | Test defaults target separate kavrigo_test; local full suite uses explicitly created kavrigo_step13_test | Explicit test DSNs must always identify disposable databases |

The model has no lease, risk-control mutation tool, database connection or exchange command tool.
Live execution remains disabled. No exchange credential enters this package. Local account and
workflow limits fail closed; do not remove them to enable unbounded production operation.

Daily risk counters are protected by a UTC-day boundary: new orders, matching and generation
advance refuse after the account's initial date until a reviewed rollover implementation exists.
Reconciliation cannot reset that boundary. This prevents yesterday's profit from offsetting
a new day's loss limit; cancellation remains available for already open orders.
