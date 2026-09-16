# Kavrigo progress

**Updated:** 2026-09-16. **Latest implementation:** step 14 local product inspection.
**Remote publication:** the user explicitly approved the direct main push on 2026-09-10.
Implementation `400e179` and handoff `d564107` were pushed successfully; `git ls-remote`
confirmed GitHub main matched local HEAD at `d564107e316311298fd80fd37133025096a63ff6`.

**Active checkpoint (2026-09-16):** `ui-ux-pro-max` was installed with explicit user
approval from upstream commit `7f69fed6a2717900085f1bc3b263721f8ba025e2`.
Step 14's local paper UI, generated OpenAPI client, and workspace inspection routes are
implemented. Full regression: **892 passed, zero skips (32.87s)**. Frontend lint, formatting,
types, build, three boundary tests and three real API browser tests passed, including axe,
mobile keyboard focus, workspace isolation and immutable versions. The explicit browser-origin
fix is verified. Step 15 observability/evals is next. See the web README for local startup.

**Starting checkpoint:** `de77742`. **Current branch:** `main` (user-directed workflow).
**Position:** local slices through step 14; next step 15 observability/evals.

### Completed local checkpoint - step 13

ADR 0027, typed contracts, migration 0002, PostgreSQL command/run receipts, fenced replay,
safe generation transitions, four Temporal workflows, outbox dispatch and the real worker are
implemented. Full regression: **885 passed, zero skips (28.98s)**, including **82 integrations**.
Ruff covers 255 files; strict typing passes 120 sources. Upgrade -> downgrade base -> upgrade
head passed in the isolated `kavrigo_step13_test` database. Both service images rebuilt.
Actual-worker health job and identical 23-event history survived a Temporal server restart.
Final daily-risk guard passed the full suite. Both final images rebuilt and the actual worker
completed another health job; API health passed. Implementation is committed as `400e179`.
Docker 28.4.0 recovered after preserving a stale runtime-socket directory; details in MACHINE_HANDOFF.

[MASTER_BUILD_SPEC.md](MASTER_BUILD_SPEC.md) and [AGENTS.md](AGENTS.md) are authoritative.
[HANDOFF.md](HANDOFF.md) records detailed limits; [MACHINE_HANDOFF.md](MACHINE_HANDOFF.md)
covers setup/persistence; [HANDOFF_PROMPT.md](HANDOFF_PROMPT.md) is the continuation prompt.

## Current outcome

Slices through step 13 are implemented locally. The durable repository reconstructs risk and
paper state from immutable PostgreSQL commands, checks hashes, and commits simulated issuance,
submission and receipts atomically. Leases fence competing writers. Reconciled terminal orders
allow generation advance with exact basis/cash/fees retained. Historical decision IDs stay deduped.
Temporal histories carry references; uncertain model dispatch stops without retrying the model.

The UI now supports versioned paper drafts and inspection of stored runs/evidence/accounts.
The full paper product milestone is **not achieved**. Product run-launch/account commands,
hosted sign-in, meaningful Nautilus strategy/data and
benchmark wiring, live data transport, paid providers, shared billing, continuous production
operation, hosted security/retention and independent review remain open. See
[ADR 0027](docs/adr/0027-durable-paper-workflows.md),
[workflow operations](docs/product/durable-workflows.md) and HANDOFF.md's earlier carry-overs.

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
| 10. Agent runtime | Local decisions/allocations | Mock workflow backend wired; hosted/authenticated routes pending |
| 11. Risk engine | Local deterministic session + durable wrapper | Shared reservations, exact sizing, fenced paper issuance; independent review pending |
| 12. Paper broker | Local broker + durable account wrapper | Exact IOC accounting/replay; generation control and capacity remain explicit |
| 13. Temporal | Implemented locally | Four workflows, PostgreSQL receipts/RLS/fencing, bounded supervision; hosted/continuous operation pending |
| 14. UI | Local product inspection implemented | Hosted auth, run launch, real chart/freshness feeds and policy editing pending |
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
| Step 13, 2026-09-10 | `python -m pytest --tb=short --junitxml=/tmp/step13-full.xml` | 885 passed, zero skips (28.98s), including 82 integrations |
| Step 13 | Ruff check/format; strict mypy across all source roots | 255 files; 120 typed sources passed |
| Step 13 | Real worker health job, Temporal restart and SDK history replay | Completed result unchanged; 23 events retained; API health ok |
| Step 13 | Alembic upgrade, downgrade base, upgrade head | Passed in newly created `kavrigo_step13_test`; application DB preserved |
| Step 14, 2026-09-16 | Full pytest with real PostgreSQL/ClickHouse/Temporal | 892 passed, zero skips (32.87s), including 89 integrations |
| Step 14 | Ruff check/format; strict mypy; OpenAPI drift | 263 Python files, 122 typed sources; snapshot matches API |
| Step 14 | Web lint/format/typecheck/test/build/generated client | Passed; three boundary tests; no generated drift |
| Step 14 | Playwright with Edge and isolated API | Three passed (19.5s): versioning, tenant switching, logout, accessibility, mobile/failure and proxy boundary |
| Historical source step 10 `c46b315` | `make check` | 680 passed / 50 integration skips; Docker unavailable |
| Historical source step 9 `3abe65d` | Full check, stack/migrations/integrations | 676 full-suite passes; dedicated 50 integrations passed |

Ignored `.local/` logs do not transfer through Git. Gitleaks/protoc/buf were not installed or
run locally. Hosted CI and independent security/CODEOWNERS review are separate; the earlier
pull-request workflow lookup for `de77742` returned no runs, which was not a CI pass.

## Next slice and safety

Next is **step 15: observability/evals**. Preserve earlier carry-overs and local-only limits.
The UI is an inspection/draft slice, not the complete end-to-end trading milestone. Hosted
telemetry credentials and paid model routing are absent; start with redacted local exports
and versioned synthetic golden evaluations.

Keep `LIVE_TRADING_ENABLED=false` and `DEFAULT_TRADING_MODE=paper`; no exchange credentials
or execution-security code. Risk supports USD spot MARKET/IOC paper/backtest, 12 fractional
places and a conservative account-wide policy union. Durable generation advance requires terminal
orders and fresh reconciliation; no prompt can release risk reservations.
Git transfers tracked source, not volumes, databases, venvs, ignored data or credentials.
Provider rights, hosted accounts, jurisdiction, domain and trademark decisions remain open.

Repository: [Ali-Zaraket/kavrigo](https://github.com/Ali-Zaraket/kavrigo). On 2026-09-09 the user
requested normal work on `main`. Main was fast-forwarded through `a1e0ecf`, preserving both
step 11 commits. Continue on `main` with ordinary non-force pushes; no PR is required for this
user-directed bootstrap workflow. Independent risk/security review remains pending before
deployment. The published `codex/deterministic-risk` branch is retained as a prior checkpoint.
Update actual commits/checks at each slice and verify the remote after pushing. Never promote
historical results or skipped integrations into verification of newer code.
