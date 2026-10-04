# Kavrigo progress

**2026-10-04 paper-launch preparation (not a launch):** Added a private, paper-only EKS Auto
Mode/ECR OpenTofu foundation with required region, private subnets, operator role and EKS KMS key; OpenTofu
1.12.0 `fmt` and `validate` passed with the pinned AWS provider. CI now validates this plan
without cloud credentials. Market trades, quotes and candles now persist an explicit
`license_ref`; the ClickHouse writer refuses an empty reference. Ingestion unit tests (14) and
real local ClickHouse integrations (10) passed, as did Ruff and strict mypy for the ingestion
package. The [paper launch review](docs/release/paper-launch-review.md) remains **NO-GO**:
there is no deployment account, active licensed provider, hosted identity, managed service
stack, completed real-data paper activation, or independent security sign-off.

**2026-10-04 CI/security and local paper checkpoint:** GitHub Actions run
[37209632714](https://github.com/Ali-Zaraket/kavrigo/actions/runs/37209632714) passed all eight jobs:
web, Python quality, PostgreSQL/ClickHouse/Temporal integration, Chromium browser, enforced Buf
contracts, secret/Trivy scan, CodeQL and container builds. Next.js and eslint-config-next are
pinned to security release 16.3.8; Trivy now blocks high/critical findings. Local web lint,
format, typecheck, four unit tests and production build pass. The patched Studio at
`http://127.0.0.1:3000/studio` and the Docker API at 58300 both return HTTP 200, including
the mode proxy and migration-aware readiness. Hosted Clerk login/MFA and managed production
infrastructure remain unverified without the corresponding accounts and settings. No licensed
market-data provider has been activated.

**2026-10-02 CI repair and hosted CSP slice:** The latest GitHub Actions run confirmed the new
browser job passed, while integration failed at ClickHouse schema setup and security could not
resolve an obsolete Trivy Action tag. A loopback-only bootstrap now applies all seven local
ClickHouse statements successfully; security pins the signed Trivy v0.36.0 commit. Hosted web
mode now configures Clerk's strict nonce CSP and dynamic provider rendering. Web lint, format,
types, four tests and production build pass locally. The CI repair is verified by the 2026-10-04
checkpoint above; real Clerk login remains to be verified.

**2026-10-02 browser CI slice:** A dedicated CI job now creates a fresh PostgreSQL service,
applies the least-privilege role and all migrations, starts a local paper-only API, builds the
web app, installs Chromium, and runs all three browser boundary tests. Failed traces are retained.
The workflow YAML parses, and the same browser suite passed locally against a separate migrated
test API. Hosted Clerk and deployment smoke tests remain separate release gates.

**2026-10-02 hosted web sign-in slice:** The Next.js shell now supports a configured Clerk
session alongside local development identity. Hosted mode presents Clerk sign-in, requests the
current session token per API call, and resets workspace/query state on account changes. The
same-origin proxy still allowlists routes and forwards only the bearer header; the API remains
the JWT, MFA and tenant authority. Nonlocal environments without hosted sign-in no longer offer
a manual token form. Web lint, format, typecheck, four unit/boundary tests and production build
pass. Three local browser tests passed against a separate migrated `kavrigo_test` API. Real Clerk
keys and a hosted session/MFA/account-switch smoke remain open. No public release is implied.

**2026-09-27 Clerk session-verification slice:** `paper-prod` now requires an explicit Clerk v2
session profile and HTTPS authorized-party allowlist. Signed v2 session tokens must carry `sid`;
pending/unknown status and a present but unlisted `azp` are refused. MFA-gated actions require a
recent second factor in Clerk's `fva`, with token elapsed time and minute-granularity uncertainty
counted against the 300-second default. The generic profile still fails closed on arrays. Local
mock sign-in remains unchanged. Full Python regression: **1066 passed, zero skips** against the
local PostgreSQL/ClickHouse/Temporal stack; Ruff check/format and strict mypy pass in the
verification container. Hosted Clerk instance setup, a real-token smoke, web sign-in and
deployment controls remain open; no public release is implied.

**2026-09-27 migration-aware readiness slice:** ADR 0044 now requires the application-role
PostgreSQL connection and the expected Alembic revision before `/readyz` returns HTTP 200.
Absent/older/branched revision rows yield a typed `schema=mismatch` and HTTP 503; a missing
version table or probe failure is `unavailable`, all within the existing two-second bound. A
test pins the expected revision to the migration head, and a real least-privilege integration
test checks the migrated database.
Full Python regression: **1044 passed** against the local stack; Ruff check/format passes 328
files and mypy covers 148 sources. Generated OpenAPI/client, web lint/format/types/three tests
and production build pass. The rebuilt local API reports PostgreSQL and schema `ok`. Worker,
provider and data-health supervision, licensed data and paper activation remain release gates.

**2026-09-27 injected-dev-provider startup slice:** The API factory now refuses an explicitly
injected `DevIdentityProvider` outside local mode, preserving the unsigned-token startup gate
even for alternate entry points. A paper-prod construction test passes. One full regression run
hit a transient PostgreSQL connection timeout in an unrelated integration case; that case passed
alone and the full rerun passed **1040 tests** against the local stack. Ruff check/format passes
328 files, mypy covers 148 sources, and the rebuilt local API is healthy. ADR 0021 records the
defense. Hosted identity validation and broader release gates remain open.

**2026-09-27 list-shaped-MFA fail-closed slice:** The generic JWT MFA interpreter no longer
equates a two-element list with a verified second factor. Current Clerk session tokens use `fva`
as factor ages, where `[7, -1]` means the second factor was never verified; mapping that to the
old generic parser would have unlocked high-impact permissions. Lists now abstain until a
provider-specific freshness policy exists. ADR 0021 and a configured-`fva` regression test record
the behavior. Full Python regression: **1039 passed** against the local stack; Ruff check/format
passes 328 files, mypy covers 148 sources, and the rebuilt local API is healthy. Hosted Clerk
claim mapping and a measured second-factor-age policy remain open.

**2026-09-27 bounded-JWKS-key slice:** Pinned PyJWT 2.13.0's optional per-key LRU has no TTL,
which could keep accepting a removed signing key after the JWKS set refreshes. The verifier now
caches only the JWKS set for 600 seconds. A rotation test replaces a key under the same `kid`,
rejects the old signature and accepts the new one. ADR 0021 records the bounded revocation
semantics. Full Python regression: **1038 passed** against the local stack; Ruff check/format
passes 328 files, mypy covers 148 sources, and the rebuilt local API is healthy. This does not
provide immediate session revocation or hosted identity setup.

**2026-09-27 secure-identity-endpoint slice:** Outside local development, JWKS authentication
now refuses to start unless both issuer and JWKS URLs are valid, credential-free HTTPS endpoints
without fragments. Local HTTP mock identity providers remain available for development. This
closes a configuration path that could otherwise fetch signing keys over plaintext transport;
it does not assert that hosted identity or claim mappings are configured. ADR 0021 records the
security rule. Full Python regression: **1037 passed** against the local stack; Ruff check/format
passes 328 files, strict mypy covers 148 sources, and the rebuilt local API is healthy.

**2026-09-27 nonblocking identity-verification slice:** The standards-based JWT verifier now
runs synchronous PyJWT JWKS key resolution off the API event loop. A concurrency test holds the
lookup and proves another coroutine can progress before it is released. Signature, issuer,
audience, expiry and MFA validation are unchanged; provider outage still fails closed. ADR 0021's
operational notes record the decision and remaining rate/capacity concern. Full Python regression:
**1021 passed** against the local PostgreSQL, Temporal and ClickHouse stack; Ruff check/format
passes 328 files and strict mypy covers 148 sources. The rebuilt API reports readiness HTTP 200.
Hosted identity configuration and deployment rate controls remain release work.

**2026-09-27 honest-readiness slice:** ADR 0044 makes `/readyz` return HTTP 503 when the
PostgreSQL tenant authority is absent, unreachable or exceeds a two-second probe bound. Configured
ClickHouse, Redpanda, Temporal and Valkey endpoints are `configured_unverified` instead of
claiming health from configuration alone. Local Compose now uses `/readyz` for the API healthcheck;
`/healthz` remains liveness. The server's paper-mode disclosure identifies current local
synthetic/testnet evidence. Full Python regression: **1020 passed** against PostgreSQL, Temporal
and ClickHouse; Ruff checks 328 files and strict typing covers 148 sources. Generated OpenAPI and
TypeScript client, web lint/format/types/three tests and production build pass. The rebuilt local
API reports readiness HTTP 200 with PostgreSQL `ok`; downstream service health remains separately
unverified by this endpoint. Licensed market data, supervised paper activation and production
release gates remain open.

**2026-09-27 reference-risk inspection slice:** ADR 0043 adds a read-only, workspace-scoped,
cursor-paginated API for the sealed reference-backtest risk journal. It rechecks the stage hash
and typed artifact before returning up to 25 receipts, their cost assumptions, reproducibility
hashes and limitations. Research now shows a compact chronological receipt view with synthetic
diagnostic labels and frozen-input disclosure. Pending, historical-unavailable and empty journals
remain distinct; there are no order controls. Tenant, viewer, pagination, cursor and corruption
tests pass. Full regression: **1017 passed** against PostgreSQL, Temporal and ClickHouse; Ruff
covers 327 files and strict typing covers 148 sources. The generated OpenAPI client, web lint,
format, types, three tests and production build pass. API readiness and Research return HTTP 200.

**2026-09-27 per-signal risk-audit slice:** ADR 0042 saves a typed, bounded receipt for each
attempted synthetic USD reference order. Each receipt binds the frozen risk request, portfolio,
supervisor controls, evaluator record, safe reason codes and any quantity handed to Nautilus.
The sealed journal validates order, identity, counts and hashes and persists with the tenant-scoped
backtest result; Temporal still carries only stage references. Audit failure refuses further order
handoffs. Historical results remain readable. These receipts are diagnostic, not broker permits;
the reference strategy remains synthetic, non-publishable and activation-ineligible. Full regression:
**1013 passed**; Ruff covers 326 files and strict typing covers 148 sources. Generated API client
description was synchronized with OpenAPI.

**2026-09-24 deterministic-risk replay slice:** ADR 0041 routes every synthetic USD reference
order signal through the real deterministic risk evaluator and one-time handoff before Nautilus
can receive it. The immutable run binds the approved agent version, global/workspace/agent policy
hashes, execution assumptions, network and supervisor controls. Risk inputs use Nautilus-owned
cash, position, P&L and open-order state; peak equity is marked on every bar. Rejections never
reach execution, and results persist evaluation/approval counts, reason codes and the replay
hash through PostgreSQL/Temporal. The bounded path refuses multi-day bars, non-candle freshness,
minimum fees and ADV impact. It is still a synthetic reference strategy with no licensed data,
so it remains non-publishable and activation-ineligible. No-signal runs complete with zero orders
and retain the replay hash. Full regression: **1002 passed** against the local stack; Ruff covers
324 files and strict typing covers 147 sources. Rebuilt API and worker started successfully;
API health/readiness and Studio return HTTP 200.

**2026-09-23 frozen-catalog slice:** ADR 0040 adds a worker-owned, read-only local Parquet
catalog for deterministic reference backtests. Run definitions carry only a canonical relative
object key plus exact byte hash, row count, instrument and interval. The loader caps object size,
parses the same bytes it hashes, requires the fixed-point Arrow schema, validates point-in-time
rows before Nautilus starts and refuses tampered or unconfigured objects without disclosing host
paths. The durable PostgreSQL/Temporal workflow passes with a catalog-backed run. No provider
data or entitlement is supplied, so results remain non-publishable and activation-ineligible.
Full regression: **990 passed** against the local stack; Ruff covers 320 files and strict typing
covers 145 sources.

**2026-09-23 deterministic reference-backtest slice:** ADR 0039 adds hash-bound, point-in-time
BTC/ETH bar fixtures and a long-only EMA diagnostic strategy for pinned NautilusTrader 1.231.0.
Single-instrument runs now exercise real decisions, cash-account orders, fills, fees, configured
slippage, Decimal equity metrics and a buy-and-hold benchmark through the durable Temporal
workflow. Every result carries five limitations, is non-publishable and cannot satisfy paper
activation. Licensed catalog data, actual agent-decision/risk replay and out-of-sample promotion
evidence remain open. Full regression: **977 passed** against the local stack; Ruff covers 316
files and strict typing covers 144 sources. Rebuilt API and worker images started successfully;
API liveness/readiness and Studio return HTTP 200.

**2026-09-23 data-entitlement slice:** ADR 0038 adds an operator-controlled, append-only ledger
for global provider rights and per-workspace data-pack access. Activation now evaluates both
scopes at the frozen evidence time and assessment time, verifies canonical event hashes, and
binds the exact event IDs/hashes into its immutable receipt. The application role is read-only;
no provider grants or user mutation route were added. Synthetic/testnet evidence remains
ineligible and activation remains inactive. Migration 0007 passed upgrade, downgrade and
reapply in the disposable database and is applied locally. Full regression: **944 passed, 25
expected integration skips**; Ruff covers 312 files, strict typing covers 143 sources, and
OpenAPI generation plus web lint/format/types/3 tests/build pass. The rebuilt API and Studio
return HTTP 200. Provider procurement, licensed durable ingestion and supervised paper
activation remain open.

**2026-09-22 paper-activation assessment slice:** ADR 0037 adds an immutable, MFA-gated
eligibility assessment bound to one agent version, approved policy hashes, evaluation input and
evaluation receipt. Seven explicit gates explain every blocker. Synthetic/testnet evidence and
unrecorded provider entitlements fail closed; activation remains inactive and execution remains
disabled. Migration 0006 passed upgrade, downgrade and reapply in the disposable database and is
applied locally. Full regression: **939 passed, 25 expected integration skips** from 964 collected;
Ruff, strict typing across 141 sources, OpenAPI generation and web lint/format/types/3 tests/build
pass. The local API and Studio both return HTTP 200. Licensed real-market evidence, entitlement
records and the actual supervised paper-activation state remain open.

**2026-09-19 public-market transport slice:** ADR 0033 adds a bounded WebSocket JSON transport
with ping/pong keepalive, reconnect through the existing pipeline, frame limits and malformed
input handling. The ingestion entry point now has an explicit local-only, 1–60 second
`CountingSink` sample; it discards provider data. A three-second sample observed 175 normalized
Binance events and 18 Coinbase events, with zero reconnects. No feed data was stored or exposed
to the product. Full regression: **954 passed, zero skips (33.82s)**; Ruff 293 files, strict
typing 136 sources, offline lock and OpenAPI checks pass. See
[ADR 0033](docs/adr/0033-public-market-websocket-sample.md). Provider rights, durable licensed
collection, frozen evaluation data, and paper approval remain open.

**2026-09-19 independent-review slice:** ADR 0032 adds one immutable, MFA-gated,
second-person review recommendation per paper-policy candidate, bound to caller-confirmed
risk/execution hashes. It is audited and idempotent; both candidate and review remain
`unapproved` and execution-disabled. Migration 0004 passed upgrade/downgrade/reapply in the
disposable test database. Full Python regression: **944 passed, zero skips**. Ruff covers 289
files; strict typing covers 136 sources. Lock/OpenAPI generation and web
lint/format/types/tests/build pass. The local app database is at 0004 and the rebuilt API is
healthy with the review route in OpenAPI. See
[ADR 0032](docs/adr/0032-non-activating-paper-policy-review.md).

**2026-09-19 policy-candidate slice:** ADR 0031 adds immutable, tenant-scoped paper risk and
execution candidate pairs with canonical hashes, audit records, mandatory idempotency and
MFA-gated writes. Read/list is workspace-scoped. Every response remains unapproved and
execution-disabled; no activation path was added. Full regression: **943 passed, zero skips
(43.71s)**. Ruff covers 286 files and strict typing 136 sources. Migration 0003 upgraded,
downgraded and re-applied in the disposable test database; lock/OpenAPI and web checks pass.
The local application database was upgraded additively; see
[ADR 0031](docs/adr/0031-unapproved-paper-policy-candidates.md).

**2026-09-18 post-step-15 slice:** Studio now launches a local synthetic paper rehearsal for
one or two USD.SIM instruments through authenticated, idempotent API submission and the real
Temporal workflow. It is labeled in Pulse, uses a separate global-killed paper account, and
cannot place an order. It is not approved policy activation or a real market-data paper run.
See [ADR 0030](docs/adr/0030-local-paper-rehearsal.md). The prior step-15 validation below
remains its own checkpoint. Final rehearsal regression: **941 passed, zero skips (34.63s)**;
Ruff on 282 Python files, strict typing on 133 sources, OpenAPI/lock checks, web
lint/format/types/tests/build, and live local Studio → Temporal → Pulse/Paper smoke all passed.

**Updated:** 2026-09-16. **Latest implementation:** step 15 local observability/evals slice.
**User direction:** Step 15 was explicitly resumed after the earlier pause. Step 14 is
published as `65998b4`; its pause checkpoint was `530ecac`. Continue normal work on main.

Step 15 adds opt-in service OTel providers, filtered console/OTLP export and a model-only
Langfuse OTLP path. API telemetry now excludes raw paths and exception messages. Thirty-one
versioned synthetic golden cases exercise real news/gateway boundaries with scripted replies.
Full regression: **935 passed, zero skips (43.93s)**. Ruff covers 277 Python files; strict
typing covers 130 sources. Real OTLP wire tests use a loopback receiver, never a hosted project.
See [observability/evals](docs/product/observability-evals.md) for usage and explicit limits.
**Remote publication:** the user explicitly approved the direct main push on 2026-09-10.
Implementation `400e179` and handoff `d564107` were pushed successfully; `git ls-remote`
confirmed GitHub main matched local HEAD at `d564107e316311298fd80fd37133025096a63ff6`.

**Active checkpoint (2026-09-16):** `ui-ux-pro-max` was installed with explicit user
approval from upstream commit `7f69fed6a2717900085f1bc3b263721f8ba025e2`.
Step 14's local paper UI, generated OpenAPI client, and workspace inspection routes are
implemented. Full regression: **892 passed, zero skips (32.87s)**. Frontend lint, formatting,
types, build, three boundary tests and three real API browser tests passed, including axe,
mobile keyboard focus, workspace isolation and immutable versions. The explicit browser-origin
fix is verified. See the web README for local startup; step 15's newer checks are above.

**Starting checkpoint:** `de77742`. **Current branch:** `main` (user-directed workflow).
**Position:** local slices through step 15; end-to-end product milestone still incomplete.

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
The full paper product milestone is **not achieved**. Order-capable paper run-launch/account commands,
hosted sign-in, licensed production-catalog agent-runtime backtests, licensed durable data
collection, paid providers, shared billing, continuous production
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
| 5. Market ingestion | Recorded replay and ephemeral public WebSocket sample | Licensed storage and Redpanda producer deferred |
| 6. Features | Deterministic point-in-time slice | Stored-window loader deferred |
| 7. Backtest | Bounded BTC/ETH reference strategy, frozen Parquet catalog and deterministic risk replay through Nautilus and Temporal | Licensed dataset builder/object storage, actual agent-runtime replay, multi-day risk accounting and out-of-sample evidence pending |
| 8. Model gateway | Local/mock | No paid provider or durable ledger |
| 9. News intelligence | Local synthetic feed | No live/durable collector |
| 10. Agent runtime | Local decisions/allocations | Mock workflow backend wired; hosted/authenticated routes pending |
| 11. Risk engine | Local deterministic session + durable wrapper | Shared reservations, exact sizing, fenced paper issuance; independent review pending |
| 12. Paper broker | Local broker + durable account wrapper | Exact IOC accounting/replay; generation control and capacity remain explicit |
| 13. Temporal | Implemented locally | Four workflows, PostgreSQL receipts/RLS/fencing, bounded supervision; hosted/continuous operation pending |
| 14. UI | Local product inspection and synthetic rehearsal launch | Hosted auth, approved real-data paper launch, real chart/freshness feeds and policy editing pending |
| 15. Observability/evals | Local service exports and synthetic golden suite implemented | Hosted project/alerts/SLOs, web traces, real-provider quality and online evals pending |

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
| Step 15, 2026-09-16 | Full pytest with real PostgreSQL/ClickHouse/Temporal | 935 passed, zero skips (43.93s), including 89 stack integrations |
| Step 15 | Ruff check/format; strict mypy; OpenAPI | 277 Python files; 130 typed sources; API snapshot unchanged |
| Step 15 | Golden suite and local OTLP HTTP receiver | 31 golden cases; privacy, replay cost, HTTP error and exporter-failure tests passed |
| Step 15 | Both service builds, console telemetry smoke, actual worker/history replay | Passed; API route spans and worker stage spans observed, health workflow completed with 23 replayed events |
| ADR 0030, 2026-09-18 | Full pytest with disposable PostgreSQL and real Temporal | 941 passed, zero skips (34.63s) |
| ADR 0030 | Ruff check/format; strict mypy; OpenAPI and uv lock | 282 Python files; 133 typed sources; contract and lock checks passed |
| ADR 0030 | Web lint/format/types/boundary tests/build; API image rebuild | Passed; three boundary tests; local API healthy |
| ADR 0030 | Browser: new workspace → paper draft → rehearsal → Pulse/Paper | Completed synthetic run `run_da9f8f4de48e5b9696315e1e47fb9885`, two NO_TRADE decisions, receipt 0 and no positions |
| ADR 0031, 2026-09-19 | Full pytest with disposable PostgreSQL and real Temporal | 943 passed, zero skips (43.71s) |
| ADR 0031 | Ruff check/format; strict mypy; uv lock/OpenAPI; web lint/format/types/tests/build | 286 Python files; 136 typed sources; all checks passed |
| ADR 0031 | Migration 0003 test DB upgrade → downgrade → upgrade | Passed; application DB additive upgrade applied |
| ADR 0034, 2026-09-21 | Binance market-data-only five-second public feed smoke | 1,311 frames; 1,310 normalized events; zero skipped; zero reconnects; count-only and non-persistent |
| ADR 0034 | Full pytest with isolated PostgreSQL and real Temporal; Ruff/format; strict mypy; uv lock/OpenAPI | 955 passed (34.61s); 295 Python files; 136 typed sources; checks passed |
| ADR 0035, 2026-09-21 | Full pytest with isolated PostgreSQL and real Temporal | 961 passed (38.83s), including authenticated testnet source persistence/inspection and bounded-sample failure |
| ADR 0035 | Ruff check/format; strict mypy; uv lock/OpenAPI; web lint/format/types/tests/build | 298 Python files; 137 typed sources; three web boundary tests and production build passed |
| ADR 0035 | Live Binance Spot Testnet → API → Temporal → agent smoke | Completed `testnet_rehearsal`; labeled evidence persisted, `no_candidates`, account sequence 0, no positions |
| ADR 0039, 2026-09-23 | Full pytest with PostgreSQL/ClickHouse/Temporal; Ruff/format; strict mypy | 977 passed; 316 Python files formatted; 144 typed sources; bounded reference workflow integration passed |
| ADR 0040, 2026-09-23 | Full pytest with PostgreSQL/ClickHouse/Temporal; Ruff/format; strict mypy | 990 passed; 320 Python files formatted; 145 typed sources; catalog workflow and tamper refusal passed |
| ADR 0041, 2026-09-24 | Full pytest with PostgreSQL/ClickHouse/Temporal; Ruff/format; strict mypy; lock/Compose | 1002 passed; 324 Python files formatted; 147 typed sources; approved, rejected, no-signal and fail-closed risk paths passed; rebuilt API/worker and Studio healthy |
| Historical source step 10 `c46b315` | `make check` | 680 passed / 50 integration skips; Docker unavailable |
| Historical source step 9 `3abe65d` | Full check, stack/migrations/integrations | 676 full-suite passes; dedicated 50 integrations passed |

Ignored `.local/` logs do not transfer through Git. Gitleaks/protoc/buf were not installed or
run locally. Hosted CI and independent security/CODEOWNERS review are separate; the earlier
pull-request workflow lookup for `de77742` returned no runs, which was not a CI pass.

## Next slice and safety

The numbered plan has local slices through step 15, with substantial explicit carry-overs.
The next product slice should add evidence-backed approval of reviewed policy candidates and wire authenticated, approved
real-data paper launch to stored decisions/risk/results. Local synthetic rehearsal already
works with placeholder draft policy IDs; it is execution-disabled. Preserve all earlier
carry-overs, notably licensed production-catalog agent-runtime backtests, hosted auth, licensed
market-data retention and operational review. No hosted telemetry
account or paid model is configured; synthetic eval passes do not measure model accuracy.

Keep `LIVE_TRADING_ENABLED=false` and `DEFAULT_TRADING_MODE=paper`; no exchange credentials
or execution-security code. Risk supports USD spot MARKET/IOC paper/backtest, 12 fractional
places and a conservative account-wide policy union. Durable generation advance requires terminal
orders and fresh reconciliation; no prompt can release risk reservations.
Git transfers tracked source, not volumes, databases, venvs, ignored data or credentials.
Provider rights, hosted accounts, jurisdiction, domain and trademark decisions remain open.

The 2026-09-21 provider review removed Coinbase from active ingestion because its current terms
restrict third-party application, derived-work display and AI-agent use without written consent.
Local validation now uses Binance's market-data-only public host and discards all values after a
bounded sample. This does not license persistent agent snapshots or UI display. CoinGecko is the
documented commercial procurement candidate; a suitable contract remains required before wiring
real prices into the agent or paper broker.

ADR 0035 now wires the public Binance Spot Testnet stream into an execution-disabled local agent
rehearsal. The source is kept as `BINANCE_TESTNET`, testnet activity is labeled simulated, only
derived evidence is frozen, and the account remains globally killed with zero exposure. This is
usable from Studio for network-to-agent validation; it is not order-capable paper activation or
licensed mainnet market evidence.

Repository: [Ali-Zaraket/kavrigo](https://github.com/Ali-Zaraket/kavrigo). On 2026-09-09 the user
requested normal work on `main`. Main was fast-forwarded through `a1e0ecf`, preserving both
step 11 commits. Continue on `main` with ordinary non-force pushes; no PR is required for this
user-directed bootstrap workflow. Independent risk/security review remains pending before
deployment. The published `codex/deterministic-risk` branch is retained as a prior checkpoint.
Update actual commits/checks at each slice and verify the remote after pushing. Never promote
historical results or skipped integrations into verification of newer code.
