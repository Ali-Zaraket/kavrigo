# Kavrigo progress

**Updated:** 2026-09-09. **Latest implementation:** `5fc9234` (step 12 local paper broker).
**Starting checkpoint:** `de77742`. **Current branch:** `main` (user-directed workflow).
**Next:** step 13 durable workflows/account recovery; independent security review remains pending.

[MASTER_BUILD_SPEC.md](MASTER_BUILD_SPEC.md) and [AGENTS.md](AGENTS.md) are authoritative.
[HANDOFF.md](HANDOFF.md) records detailed limits; [MACHINE_HANDOFF.md](MACHINE_HANDOFF.md)
covers setup/persistence; [HANDOFF_PROMPT.md](HANDOFF_PROMPT.md) is the continuation prompt.

## Current outcome

Slices through step 12 are implemented, with steps 8–12 local/mock only. The Windows
destination was rebuilt with fresh local databases and the baseline passed before new work.
Deterministic risk now binds frozen decisions/allocations, checks policy independently, sizes
with exact fixed point, reserves resources across agents and permits one-time paper handoff
after freshness/control/fencing rechecks. The local paper broker now receives actual risk
issuance, simulates finite-depth IOC fills, accounts for cash/basis/fees/P&L, and reconciles
missed fills by replaying a bounded journal. The mock model → runtime → risk → paper path is tested.

The full paper product milestone is **not achieved**. Risk and paper authority are in memory,
limited to one batch generation with retained risk reservations. Durable reservations/audit,
process-restart recovery, continuous operation, workflows,
meaningful backtest strategy/data wiring and UI remain open. See
[ADR 0026](docs/adr/0026-local-paper-broker.md) and [paper behavior](docs/product/paper-broker.md).

## Build sequence

| Step | State | Limits |
|---|---|---|
| 1. Bootstrap | Implemented locally | Hosted CI/review separate |
| 2. Contracts | Pydantic and Protobuf source | Protobuf compilation/generation pending |
| 3. Local development | Destination rebuild/migration passed | 50 integrations passed; current Docker state in machine notes |
| 4. Auth / tenants | Implemented slice | Real Clerk config and membership mutation routes deferred |
| 5. Market ingestion | Recorded/scripted slice | Live transport and Redpanda producer deferred |
| 6. Features | Deterministic point-in-time slice | Stored-window loader deferred |
| 7. Backtest | Contracts/engine configuration | No strategy/data wiring or meaningful BTC/ETH run |
| 8. Model gateway | Local/mock | No paid provider or durable ledger |
| 9. News intelligence | Local synthetic feed | No live/durable collector |
| 10. Agent runtime | Local decisions/allocations | No deployed worker |
| 11. Risk engine | Local deterministic session | Shared reservations, exact sizing, one-time permit; durable operation/review pending |
| 12. Paper broker | Local batch implemented | Exact orders/fills/accounting, missed-fill reconciliation/replay; no process-restart durability |
| 13. Temporal | Next | Durable workflows, account ownership, receipts/outbox and paper supervision |
| 14. UI | Not started | Frontend skill requirement in HANDOFF.md §7 |
| 15. Observability/evals | Dedicated step pending | Existing OTel/local audit; hosted export and broader golden evals pending |

All carry-overs and reasons remain in [HANDOFF.md §5](HANDOFF.md#5-deferred-work--read-this-before-starting-anything).

## Recorded verification

Destination checks used Linux Docker Python 3.13.11 and the equivalent Python commands for
`make check`; no host Python 3.13 venv or provider key was used. Commands are in MACHINE_HANDOFF.md.

| Checkpoint | Checks | Actual result |
|---|---|---|
| Baseline `de77742`, 2026-09-08/09 | Ruff check/format, mypy, pytest | 730 passed, zero skips; 208 formatted files, 99 typed sources |
| Baseline | Compose rebuild, migration, dedicated integrations | Healthy stack, migration applied, 50 passed / 680 deselected |
| Step 11 `97c4d60`, 2026-09-09 | Ruff check/format, mypy `--strict`, pytest | 219 formatted files, 105 typed sources; 806 passed, zero skips (14.43s) |
| Step 11 | `pytest -m integration` | 50 passed / 756 deselected (5.76s) |
| Step 11 | Risk tests with coverage | 76 passed, 94% (573 statements, 37 missed) |
| Step 11 | Float-money AST guard; `git diff --check` | 105 sources passed; no whitespace errors |
| Step 11 | Compose config, rebuild, health wait, Alembic upgrade | Passed; six health-checked services healthy, skeleton worker running |
| Step 12 `5fc9234`, 2026-09-09 | Ruff check/format, mypy `--strict`, pytest | 232 formatted files, 110 typed sources; 847 passed, zero skips (15.52s) |
| Step 12 | `pytest -m integration` | 50 passed / 797 deselected (6.28s) |
| Step 12 | Paper/risk tests with paper coverage | 117 passed (41 paper + 76 risk), 94% paper coverage (559 statements, 33 missed) |
| Step 12 | Float-money AST guard; `git diff --check` | 110 sources passed; no whitespace errors |
| Step 12 | Compose config, both image rebuilds, health wait, Alembic upgrade, API health | Passed; API uses host 58300 because Windows excluded 58000 |
| Historical source step 10 `c46b315` | `make check` | 680 passed / 50 integration skips; Docker unavailable |
| Historical source step 9 `3abe65d` | Full check, stack/migrations/integrations | 676 full-suite passes; dedicated 50 integrations passed |

Ignored `.local/` logs do not transfer through Git. Gitleaks/protoc/buf were not installed or
run locally. Hosted CI and independent security/CODEOWNERS review are separate; the earlier
pull-request workflow lookup for `de77742` returned no runs, which was not a CI pass.

## Next slice and safety

Follow [HANDOFF.md §10](HANDOFF.md#10-your-next-task--step-13-durable-workflows-and-account-recovery).
Define durable PostgreSQL ownership, receipts/idempotency, audit/outbox and safe risk generation
transitions before continuous operation. Implement Temporal evaluation/backtest/data-health and
paper supervision workflows. Preserve unknown acknowledgement handling; never reset risk from
a stale portfolio. Existing replay restores a broker view over the same live simulator only.
Retain all earlier deferrals.

Keep `LIVE_TRADING_ENABLED=false` and `DEFAULT_TRADING_MODE=paper`; no exchange credentials
or execution-security code. Risk supports USD spot MARKET/IOC paper/backtest, 12 fractional
places, a conservative account-wide policy union and no reservation release/reset API.
Git transfers tracked source, not volumes, databases, venvs, ignored data or credentials.
Provider rights, hosted accounts, jurisdiction, domain and trademark decisions remain open.

Repository: [Ali-Zaraket/kavrigo](https://github.com/Ali-Zaraket/kavrigo). On 2026-09-09 the user
requested normal work on `main`. Main was fast-forwarded through `a1e0ecf`, preserving both
step 11 commits. Continue on `main` with ordinary non-force pushes; no PR is required for this
user-directed bootstrap workflow. Independent risk/security review remains pending before
deployment. The published `codex/deterministic-risk` branch is retained as a prior checkpoint.
Update actual commits/checks at each slice and verify the remote after pushing. Never promote
historical results or skipped integrations into verification of newer code.
