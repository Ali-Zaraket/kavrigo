# Kavrigo progress

**Updated:** 2026-09-09. **Latest implementation:** `97c4d60` (step 11 local risk).
**Starting checkpoint:** `de77742`. **Work branch:** `codex/deterministic-risk`.
**Next:** step 12 paper broker; independent review of risk remains pending.

[MASTER_BUILD_SPEC.md](MASTER_BUILD_SPEC.md) and [AGENTS.md](AGENTS.md) are authoritative.
[HANDOFF.md](HANDOFF.md) records detailed limits; [MACHINE_HANDOFF.md](MACHINE_HANDOFF.md)
covers setup/persistence; [HANDOFF_PROMPT.md](HANDOFF_PROMPT.md) is the continuation prompt.

## Current outcome

Slices through step 11 are implemented, with steps 8–11 local/mock only. The Windows
destination was rebuilt with fresh local databases and the baseline passed before new work.
Deterministic risk now binds frozen decisions/allocations, checks policy independently, sizes
with exact fixed point, reserves resources across agents and permits one-time paper handoff
after freshness/control/fencing rechecks. No broker or venue receives orders yet.

The full paper product milestone is **not achieved**. Risk is an in-memory account session.
Durable reservations/audit, canonical paper orders/fills, reconciliation, workflows,
meaningful backtest strategy/data wiring and UI remain open. See
[ADR 0025](docs/adr/0025-local-deterministic-risk.md) and [risk behavior](docs/product/deterministic-risk.md).

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
| 12. Paper broker | Next | Orders, fills, cash/positions, fees, P&L, reconciliation/replay |
| 13. Temporal | Not started | Durable workflows and paper supervision |
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
| Historical source step 10 `c46b315` | `make check` | 680 passed / 50 integration skips; Docker unavailable |
| Historical source step 9 `3abe65d` | Full check, stack/migrations/integrations | 676 full-suite passes; dedicated 50 integrations passed |

Ignored `.local/` logs do not transfer through Git. Gitleaks/protoc/buf were not installed or
run locally. Hosted CI and independent security/CODEOWNERS review are separate; the earlier
pull-request workflow lookup for `de77742` returned no runs, which was not a CI pass.

## Next slice and safety

Follow [HANDOFF.md §10](HANDOFF.md#10-your-next-task--step-12-paper-broker) for the paper broker.
Define authoritative ledger/reconciliation before releasing reservations; authenticate risk
issuance and enforce cash/quantity ceilings, expiry, fencing and client-order idempotency.
Add duplicate, partial/out-of-order fill, reconnect and crash replay tests. Retain all deferrals.

Keep `LIVE_TRADING_ENABLED=false` and `DEFAULT_TRADING_MODE=paper`; no exchange credentials
or execution-security code. Risk supports USD spot MARKET/IOC paper/backtest, 12 fractional
places, a conservative account-wide policy union and no reservation release/reset API.
Git transfers tracked source, not volumes, databases, venvs, ignored data or credentials.
Provider rights, hosted accounts, jurisdiction, domain and trademark decisions remain open.

Repository: [Ali-Zaraket/kavrigo](https://github.com/Ali-Zaraket/kavrigo). Publish
`codex/deterministic-risk` through a PR; independent review is pending and `main` is unchanged.
Update actual commits/checks at each slice and verify the remote after pushing. Never promote
historical results or skipped integrations into verification of newer code.
