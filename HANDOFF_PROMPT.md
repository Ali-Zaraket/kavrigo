# Prompt for the next agent

Open the transferred repository on the destination machine, then paste everything below the
line into Codex. The repository contains all referenced handoff files.

---

You are the principal engineering agent for **Kavrigo**, a paper-first, evidence-first platform
for building AI crypto trading agents. This is an in-progress build, not a greenfield one.

## Read first, in this order

1. `AGENTS.md` — your brief and the non-negotiable domain rules. This is the authority.
2. `MASTER_BUILD_SPEC.md` — the product and architecture specification.
3. `PROGRESS.md` — the concise checkpoint, verification results and next slice.
4. `HANDOFF.md` — the current state of play: what exists, what was deliberately deferred, the
   environment's quirks, and the traps that already cost hours to find.
5. `MACHINE_HANDOFF.md` — GitHub cloning, setup and data persistence on this machine.
6. The most recent commit messages (`git log`). They are long on purpose and record *why*,
   including bugs found and alternatives rejected.

## Where things stand

Latest implementation is `400e179` (step 13) on `main`. Final checks: 885 tests, zero skips,
82 integrations; ruff on 255 files and strict typing on 120 sources. See PROGRESS.md.
PostgreSQL now owns durable paper account commands, receipts, run inputs/stages and an outbox.
The real worker registers four Temporal workflows for evaluation, backtests, health and bounded
paper supervision. Forced RLS, account row locks, DB-clock leases, immutable receipts and exact
replay protect process recovery. The default model explicitly abstains with a zero-cost mock.
Read ADRs 0025-0027 and retain every carry-over in HANDOFF.md §5.

Workflows carry references, not frozen financial/evidence bodies. Unknown model dispatch becomes
`uncertain` without another provider call. Risk issuance, simulated submission and stage receipt
commit together. Generation advance requires terminal orders and fresh reconciliation with exact
basis retained. Accounts stop accepting orders/matching/advance across the initial UTC day;
reviewed daily rollover, compaction and continuous production operation are still deferred.
Nautilus strategy/data/benchmark wiring remains incomplete; its empty result is refused.

Docker Python 3.13.11 is the verification environment; the host has no Python 3.13 venv.
Use `$env:KAVRIGO_API_HOST_PORT='58300'` for Compose because Windows reserved 58000.
API integration tests truncate their configured database: use separate disposable test DSNs,
never the application's `kavrigo` database. This machine has `kavrigo_step13_test`; defaults target
`kavrigo_test`. Apply migration 0002 independently to application and test databases.

Docker recovered on 2026-09-10 by preserving a stuck runtime-socket directory; see
MACHINE_HANDOFF.md. Do not factory-reset, delete volumes, or reinstall tools to resume.
Temporal now persists history in `temporal-data`; the actual worker's completed result and history
survived a server restart. Check current Docker/Git state rather than assuming services stayed up.

**Next: step 14 Product UI**, following HANDOFF.md §§7 and 10. Resolve the explicit frontend
skill requirement before implementation. Add authenticated, workspace-scoped API interfaces
for the internal repositories before exposing mutations in the UI. Preserve paper/live distinction,
immutable version bindings, idempotency, freshness and evidence provenance. Do not fabricate P&L
or meaningful backtest results to fill the interface. Step 15 observability/evals follows.

Continue on `main` with separate slice commits and ordinary non-force pushes, as the user directed.
No PR is required for the bootstrap workflow. Independent security review remains a deployment gate.
Do not repeat completed steps 8-13 or treat local integration as production readiness.

## How to work

Follow `AGENTS.md` § "Engineering workflow" for every task: state which requirement or ADR you
are implementing, inspect existing contracts before adding new ones, verify external API
behaviour against current official documentation, write typed contracts first, implement the
smallest vertical slice, test at a level appropriate to the risk, add observability, and run the
checks before reporting completion.

Verify with:

```bash
make check                        # ruff + mypy --strict + pytest
make up && make migrate           # local stack (ports are in a 5xxxx range — see HANDOFF.md §4)
make test-integration             # configure a separate migrated test database first
```

Commit each completed step separately on `main`, with a message that explains
the reasoning and names anything you deferred. Update `PROGRESS.md` and the relevant handoff
documents with the actual checks and remaining work. Follow the current user-directed workflow
in `CONTRIBUTING.md`; do not force-push or bypass remote branch protections.

## Things that will get you into trouble

- **Do not write provider or vendor API shapes from memory.** Every venue message format and
  every third-party signature in this repo was fetched from official documentation and carries
  the source URL and verification date. `AGENTS.md` requires this. When a doc page does not
  state something, leave it configurable and say so rather than inventing a plausible number.
- **Do not weaken the safety gates.** `LIVE_TRADING_ENABLED=true` and `AUTH_PROVIDER=dev` outside
  a local environment both make the process refuse to start. They are startup refusals, not
  runtime branches, and must stay that way.
- **Do not put code in `kavrigo-execution-security/`.** It is a deployment and access boundary
  that stays empty until it is a separate restricted repository (ADR 0017).
- **Do not use binary floats for money or quantity**, and do not let unvalidated model JSON into
  the domain.
- **Do not change architecture silently.** Write an ADR (`docs/adr/0000-template.md`).
- **When a test is flaky, find the cause.** The last session traced an intermittent failure to a
  ClickHouse TTL deleting backdated test rows — three separate causes, none of them the sink
  that appeared to be losing data. Re-running until green would have shipped a real trap.

## Report honestly

When you finish a step, say plainly what you built, exactly which checks you ran and their
results, and what you left undone and why. Never describe something as verified that you did not
run, or as production-ready because it compiles. Deferred work goes in `HANDOFF.md` §5 so it is
not lost.
