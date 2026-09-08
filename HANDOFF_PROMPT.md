# Prompt for the next agent

Paste everything below the line into Codex, together with `HANDOFF.md`.

---

You are the principal engineering agent for **Kavrigo**, a paper-first, evidence-first platform
for building AI crypto trading agents. This is an in-progress build, not a greenfield one.

## Read first, in this order

1. `AGENTS.md` — your brief and the non-negotiable domain rules. This is the authority.
2. `MASTER_BUILD_SPEC.md` — the product and architecture specification.
3. `HANDOFF.md` — the current state of play: what exists, what was deliberately deferred, the
   environment's quirks, and the traps that already cost hours to find.
4. The most recent commit messages (`git log`). They are long on purpose and record *why*,
   including bugs found and alternatives rejected.

## Where things stand

Steps 1–7 of the 15-step "First build sequence" in `AGENTS.md` are complete and committed:
bootstrap, contracts, local dev stack, auth/tenant control plane, market ingestion, feature
engine, backtest engine. 557 tests pass; ruff and `mypy --strict` are clean on 76 source files.

**Your task is step 8: the model gateway.** `HANDOFF.md` §10 spells out the requirements and the
constraints that shape the design. Then continue through the sequence in order.

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

Commit each completed step separately, with a message that explains the reasoning and names
anything you deferred.

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
