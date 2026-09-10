# Durable paper workflows

Step 13 implements ADR 0027: PostgreSQL owns paper accounts and run artifacts; Temporal
coordinates bounded business workflows using references and hashes. All operation is local
and paper-only. There is no exchange adapter, private credential, or live execution path.

## Run a workflow

Apply migration `0002` as the database owner before accepting jobs. The engine worker connects
as `kavrigo_app`, subject to forced workspace RLS. It registers `AgentEvaluationWorkflow`,
`BacktestWorkflow`, `DataHealthWorkflow`, and `PaperSupervisionWorkflow` on
`kavrigo-paper-v1` in the local `default` Temporal namespace. The local server stores its
history in the `temporal-data` named volume; ordinary container restarts preserve it.

Trusted Python callers construct a frozen `RunDefinition`, then call
`await RunRepository(database).create(definition)`. Creation commits the input/hash and a
`run.queued` outbox event together. Set `KAVRIGO_WORKER_WORKSPACES` to a comma-separated
allowlist of existing workspace IDs for automatic dispatch. Its default is empty: the worker
polls Temporal but does not enumerate all tenants or invent accounts. Alternatively call
`start_run(client, runs, ref, queue)` explicitly after creation. Use the Pydantic data converter.
These are internal service interfaces; authenticated product API routes remain a later slice.

Dispatch uses a stable workspace/run workflow ID and rejects duplicate starts. An unknown
start acknowledgement leaves the outbox event pending. Retrying resumes the existing workflow;
terminal PostgreSQL stage receipts prevent repeat domain execution even after Temporal history
retention. Failed workflows need operator diagnosis; dispatch never resets them automatically.

Agent evaluation freezes its registration, snapshot, portfolio, evidence and market inputs in
PostgreSQL. The activity commits a dispatch marker before calling the runtime. If an earlier
model dispatch has no receipt, it records `uncertain` and sends no orders. A late response cannot
rewrite that result. The default worker uses the actual local model gateway/runtime with a
zero-cost mock that returns `UNKNOWN`/`NO_TRADE`; paid provider routes are absent. The local
model budget ledger is not a durable multi-process billing implementation.

The execution activity converts the runtime's portfolio allocations into paper intents and
uses the deterministic risk engine. It checks the frozen portfolio against the account's
current generation. Risk issuance, simulated order acceptance, account journal and execution
stage receipt commit in one PostgreSQL transaction. Market observations enter through
`AccountRepository.commit` directly; ticks are not Temporal workflow events.

The backtest activity invokes the existing Nautilus adapter and preserves its reproducibility
bundle. Its current zero-decision result makes the workflow `refused`, not meaningful completed
research. Strategy/data wiring and benchmark results remain an explicit step 7 carry-over.

Data health checks freshness, unhealthy status, sequence gaps, clock drift and source divergence;
failed checks emit a `data.unhealthy` outbox event. These frozen observations are not a live
collector. Paper supervision performs 1-20 reconciliation cycles, separated by durable timers,
and stops on an unreconciled result. It ages existing marks without claiming new market data.
There is no automatic incident pager, rescheduling daemon, or provider reconnect loop yet.

## Account ownership and recovery

Create an `AccountDefinition` once, then acquire a database lease for each writer. Each command
locks the account row, validates database-time ownership, reconstructs and verifies the prior
journal, applies the command, and rechecks lease expiry before commit. The monotonic database
lease token fences process ownership; the domain risk-control token separately invalidates
risk permits. Neither token can bypass deterministic risk checks. A stale lease may retrieve
an already committed receipt but cannot write a new command.

Retain the same command key after an unknown acknowledgement. Identical keys return the original
receipt; conflicting payloads fail. Market instrument/sequence duplicates are also checked.
The journal retains rejected decisions and prior generations, preventing their reuse. Generation
advance requires terminal orders and a fresh reconciled portfolio. Exact cost basis, cash, fees,
marks, peak equity and P&L carry forward; rounded average prices never seed the next generation.
Control refresh and generation advance are explicit trusted commands, never model tools.

Recovery checks recorded command and state hashes before accepting new writes. This is a bounded
implementation: 1,000 commands and 10 MB of retained serialized account artifacts. At capacity it
fails closed; compaction, archival and performance at production volume are deferred. Historical
reads return their recorded `as_of`; callers must not display them as current market prices.
Code changes affecting replay require compatibility work and history replay checks before rollout.

## Security and operations

All five engine tables use forced RLS. Commands are append-only; frozen inputs, terminal stage
results and outbox payloads are protected by database triggers and restricted grants. PostgreSQL
is the only financial authority. Temporal history carries references/statuses, and activities
replace exception details with closed error codes to avoid leaking SQL parameters or evidence.
The trusted local worker is not a tenant authentication boundary. Cloud namespace authentication,
least-privilege deployment separation, encryption/retention controls and independent review remain.

OTel spans `account.command` and `workflow.stage`, counters `kavrigo.account.commands` and
`kavrigo.workflow.stages`, and metadata logs report command/stage outcomes. Historical risk replay
uses no-op telemetry. The transactional outbox records account updates, run creation/completion
and unhealthy data. Only `run.queued` is dispatched here; other consumers and hosted export are
pending. Metrics describe attempts/replays, not an exactly-once billing ledger.

On rollback, stop workers and preserve PostgreSQL journals and Temporal history. Do not downgrade
the active account database or restart an old in-memory broker over a durable account. Migration
rollback tests must use a disposable database; API integration fixtures truncate their configured
test database, including dependent engine tables. Defaults now target `kavrigo_test`, never the
application database. Set both test DSNs explicitly when using a different disposable database.

## Verification

Tests exercise real PostgreSQL RLS/triggers, duplicate commands, rollback before commit, a lost
acknowledgement after commit, exact generation carry-forward, expired and replaced leases, a
separate Python process reading recovered state, real Temporal worker replacement, uncertain
model dispatch, the actual mock-runtime-to-risk-to-paper path, Nautilus refusal, and SDK history
replay. See PROGRESS.md for the exact latest run results and remaining limitations.

Daily P&L rollover is deliberately not implicit: new orders, market matching and generation
advance are refused across the account's initial UTC date. Cancellation and reconciliation
remain available. A reviewed durable day-rollover command is required before multi-day operation;
yesterday's gains must not offset today's risk limits.
