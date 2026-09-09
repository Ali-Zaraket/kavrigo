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

The Windows destination baseline `de77742` was restored and verified before step 11.
Latest implementation is `5fc9234`, on `main`: local paper orders/fills, exact cash/basis/fees/P&L,
issued-risk guards, idempotent receipts and replay reconciliation. Read ADRs 0025–0026 and all
deferrals in HANDOFF.md §5. Steps 8–12 remain local/mock only. Paper is a single-generation
batch; there is no deployed risk/paper service, continuous operation or process-restart
durability. Independent security review is pending; no live execution exists.

Docker Python 3.13.11 checks passed: **847 tests, zero skips**, ruff check/format on 232 files,
mypy `--strict` on 110 sources; dedicated integrations **50 passed / 797 deselected**.
Both service images rebuilt, stack/API health and Alembic upgrade passed. Paper/risk tests
passed 117 (41 paper + 76 risk), with 94% paper coverage. Docker recovered after the user's
restart; use `$env:KAVRIGO_API_HOST_PORT='58300'` in PowerShell because Windows reserved 58000.
See MACHINE_HANDOFF.md for exact commands and current Docker status.
No host Python 3.13 venv or tool installation was performed. Verify branch/commit and the
current stack before work; preserve existing destination volumes rather than reinitializing them.

**Implement step 13: durable workflows and account recovery**, following HANDOFF.md §10.
Define PostgreSQL ownership/fencing, receipts/idempotency, audit/outbox and safe risk generation
transitions before enabling continuous operation. Add Temporal evaluation, backtest, data-health
and paper supervision workflows using the local dev server. Never release reservations after
an ambiguous handoff or rebuild a risk session from a stale portfolio. Test actual durable
worker/process recovery; existing replay only restores broker views over the same live venue.
Retain the pending meaningful Nautilus BTC/ETH strategy/data wiring and all earlier deferrals.

Continue in order and commit each slice separately on `main`, as the user requested on
2026-09-09. Use ordinary non-force pushes; the prior work-branch/PR requirement is superseded.
Independent risk/security review remains required before deployment. Do not restart
steps 8–12. Step 14's frontend skill requirement remains in HANDOFF.md §7.

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
make test-integration             # needs the stack; skips cleanly without it
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
