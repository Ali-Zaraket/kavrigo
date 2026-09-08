# Kavrigo progress

**Updated:** 2026-09-08. **Latest implementation:** `c46b315` (step 10).
**Prior handoff checkpoint:** `6ec6781`. **Next:** destination stack verification, then step 11.

This is the concise project checkpoint for switching machines or starting a new task.
[MASTER_BUILD_SPEC.md](MASTER_BUILD_SPEC.md) and [AGENTS.md](AGENTS.md) remain authoritative.
[HANDOFF.md](HANDOFF.md) holds the detailed implementation limits and engineering notes;
[MACHINE_HANDOFF.md](MACHINE_HANDOFF.md) covers cloning, setup and data persistence;
[HANDOFF_PROMPT.md](HANDOFF_PROMPT.md) is the copy/paste continuation prompt.

Cross-checked on 2026-09-08 against the Kavrigo task **“Implement model gateway”**, its final
verification output and Git history. That task ended at `6ec6781` after preparing and checking
a transfer bundle; Docker cleanup failed and no step 11 implementation followed. This file
preserves the relevant outcome without requiring access to that task on another machine.

## Current outcome

The repository contains committed slices through step 10 of the build sequence. The complete
paper-trading product milestone is **not achieved**: deterministic risk evaluation, a paper
broker, workflow wiring and the web UI are still pending. The latest runtime produces structured
decisions and inert portfolio proposals; it cannot approve or execute an order.

Implementation was paused for a machine transfer. This progress/handoff update changes only
documentation and does not resume step 11 or recover the source machine's Docker installation.

## Build sequence

| Step | State at this checkpoint | Evidence / limits |
|---|---|---|
| 1. Bootstrap | Implemented locally | Repository boundaries, ADRs, security docs and CI configuration; hosted CI results unverified here |
| 2. Contracts | Pydantic contracts and Protobuf source present | Protobuf compiler validation/generation remains pending |
| 3. Local development | Compose configuration present; earlier stack run passed | Final step 10 stack verification remains pending |
| 4. Auth / tenant control plane | Implemented slice | RLS, agent CRUD, immutable versions and idempotency; real Clerk configuration and membership mutation routes deferred |
| 5. Market ingestion | Recorded/scripted data slice | Venue normalization, freshness/replay and ClickHouse sink; live transport and Redpanda producer deferred |
| 6. Feature engine | Implemented slice | Deterministic point-in-time features; stored-window loader deferred |
| 7. Backtest engine | Contracts and engine configuration | No strategy/data wiring or meaningful deterministic BTC/ETH backtest yet |
| 8. Model gateway | Local/mock slice | Exact in-process budgets, validation, replay and trace hooks; no paid/network provider or durable ledger |
| 9. News intelligence | Local synthetic-feed slice | Exact dedupe, validated extraction and frozen evidence; no live feed or durable collector |
| 10. Agent runtime | Local decision/allocation slice | Frozen inputs, server-bound decisions, inert portfolio allocations; no deployed worker or order approval |
| 11. Risk engine | Next; evaluator not implemented | Risk contracts exist; deterministic approval and property/replay checks remain |
| 12. Paper broker | Not started | Canonical order state, fills, cash/positions, fees, P&L and replay |
| 13. Temporal workflows | Not started | Durable evaluations, backtests, data health and paper supervision |
| 14. Product UI | Not started | See the recorded frontend skill requirement in HANDOFF.md §7 |
| 15. Observability / evals | Dedicated step not started | Earlier services have logging/OTel hooks; hosted export and broader golden evals remain |

Full deferrals and their reasons are in [HANDOFF.md §5](HANDOFF.md#5-deferred-work--read-this-before-starting-anything).

## Recorded verification

These are historical results from the implementation checkpoints, not fresh results from this
documentation update or from another machine.

| Checkpoint | Checks | Recorded result |
|---|---|---|
| Step 10, `c46b315` | `make check` | 680 passed, 50 integration tests skipped; ruff/format clean on 206 files; strict mypy clean on 99 source files |
| Step 10, `c46b315` | `.venv/bin/python -m pytest -m 'not integration'` | 680 passed, 50 deselected |
| Step 10, `c46b315` | `make up && make migrate && make test-integration` | `make up` stalled and was cancelled; chained commands did not run |
| Step 9, `3abe65d` | `make check`; `make up && make migrate && make test-integration` | 676 tests passed in the full check; stack build/migrations and all 50 integrations passed |

The source Docker daemon remained unreachable after recovery attempts. No database export or
successful image/cache cleanup was verified. Preserve required source data; see
[Docker persistence](MACHINE_HANDOFF.md#docker-persistence-and-endpoints).

## Next authorized implementation slice

When the user resumes implementation on the destination machine:

1. Follow [MACHINE_HANDOFF.md](MACHINE_HANDOFF.md) to clone the handoff branch and rebuild the
   environment. Run the listed checks and record the actual commit, date and pass/skip counts.
   The checkpoint expects **50 integration passes**, not skipped database tests.
2. Inspect the existing risk, order, portfolio, freshness and runtime contracts. Implement
   step 11 under [ADR 0004](docs/adr/0004-deterministic-risk-outside-llm.md), following
   [HANDOFF.md §10](HANDOFF.md#10-your-next-task--step-11-deterministic-risk).
3. Prove rejected intents cannot reach execution, limits cannot be exceeded, stale data rejects
   and duplicate intents are idempotent. Keep approval independent of model/runtime output.
4. Record remaining limits and exact validation before advancing to the paper broker.

## Safety and portability

- Keep `LIVE_TRADING_ENABLED=false` and `DEFAULT_TRADING_MODE=paper`.
- Preserve the separate execution-security boundary; no exchange secrets or live execution.
- Git carries tracked source and these documents. It does not transfer Docker volumes,
  databases, `.venv`, ignored datasets, credentials or local conversation history.
- Provider rights, hosted accounts, domain acquisition and trademark clearance remain open.
- The GitHub remote is now configured for [Ali-Zaraket/kavrigo](https://github.com/Ali-Zaraket/kavrigo).
  This documentation change uses `codex/progress-handoff`; follow the repository's branch/PR
  policy rather than pushing directly to `main`.

## Keep this checkpoint useful

At each completed slice or machine switch, update this file's implementation commit, step
status, actual verification results and next action. Put detailed limits in `HANDOFF.md`, setup
changes in `MACHINE_HANDOFF.md`, and refresh `HANDOFF_PROMPT.md` if the starting task changes.
Commit and push the documents with the relevant changes, then verify the remote branch points
to the expected commit. Record failed or skipped checks explicitly; never promote a historical
pass into verification of newer code.
