# Kavrigo — engineering handoff

**Written:** 2026-09-08 · **Position:** steps 1–7 of 15 complete · **Next:** step 8 (model gateway)

You are picking up an in-progress build. Read `AGENTS.md` and `MASTER_BUILD_SPEC.md` first —
they are the authority. This document is the *state of play*: what exists, what was deliberately
left undone, and the things that already cost someone an hour to discover.

---

## 1. How the work is organised

`AGENTS.md` § "First build sequence" is a numbered 15-step plan. Execute it **in order** unless
blocked by a concrete dependency. Every session so far has advanced it one step and committed.

| # | Step | State |
|---|---|---|
| 1 | Repository / bootstrap | done |
| 2 | Contracts | done |
| 3 | Local development | done, **partly unverified** — see §5 |
| 4 | Auth / tenant control plane | done |
| 5 | Market ingestion | done **except the live WebSocket transport** — see §5 |
| 6 | Feature engine | done |
| 7 | Backtest engine | done **except the strategy layer** — see §5 |
| 8 | Model gateway | **← you are here** |
| 9 | News intelligence | not started |
| 10 | Agent runtime | not started |
| 11 | Risk engine | not started |
| 12 | Paper broker | not started |
| 13 | Temporal workflows | not started |
| 14 | Product UI | not started — has a **specific tooling instruction**, see §7 |
| 15 | Observability / evals | not started |

The milestone all of this is aimed at (`AGENTS.md`, last line):

> A user can create a versioned paper-only AgentSpec, ingest/replay BTC/ETH market data, run a
> deterministic backtest, receive a structured evidence-backed decision, pass it through
> deterministic risk, and see the result in the web UI — with no private exchange credential
> involved.

---

## 2. Commits so far

```text
6be11f9  Fix intermittent ClickHouse test failures: TTL, Replacing key, isolation
fa03130  Backtest engine: manifests, cost realism, metrics, Nautilus adapter   (step 7)
637823b  Feature engine: deterministic, versioned, point-in-time features      (step 6)
ce50933  Market ingestion: venue adapters, normalization, stream health, sinks (step 5)
b62bfda  Bootstrap Kavrigo: contracts, local stack, and tenant control plane   (steps 1-4)
```

Commit messages are long on purpose — they record *why*, including bugs found and rejected
alternatives. Read the one for the step you are extending. Nothing has been pushed; there is no
remote yet.

---

## 3. Repository map

A **bootstrap monorepo**. The five repos from `MASTER_BUILD_SPEC.md` §17 are mirrored as
top-level directories until the GitHub org exists (`docs/repo-split-plan.md`).

```text
kavrigo-engine/
  libs/domain/              Pydantic domain contracts + the shared decimal context
  libs/data-contracts/      Protobuf wire contracts (never generated — see §5)
  libs/market-data/         venue adapters, normalization, stream health, replay
  libs/signals/             deterministic, versioned, point-in-time feature engine
  libs/backtest/            dataset manifests, cost models, metrics, reproducibility
  libs/nautilus-adapter/    the ONLY package that may import a NautilusTrader symbol
  services/market-ingestion/  pipeline, envelopes, ClickHouse sink
  services/engine-worker/   skeleton; remaining services land here
kavrigo-platform/
  services/api/             FastAPI control plane + Alembic migrations
  apps/web/                 empty — step 14
kavrigo-execution-security/ BOUNDARY PLACEHOLDER — must stay empty, see §6
kavrigo-infra/local/        docker compose stack, Dockerfiles, DB bootstrap
kavrigo-research/           empty
docs/adr/                   21 ADRs (0001–0021) + template + index
```

---

## 4. Environment — verified quirks, not guesses

**Host ports are in a 5xxxx range.** Port 5432 was occupied by an unrelated project on the dev
machine, so the whole stack was remapped. Container-internal ports are unchanged.

| Service | Host port |
|---|---|
| PostgreSQL | **55432** |
| ClickHouse HTTP | **58123** |
| Redpanda Kafka | 59092 |
| Valkey | 56379 |
| Temporal | 57233 (UI 58233) |
| API | 58000 |

**Two PostgreSQL roles, and the split is load-bearing.** `kavrigo` owns the schema and runs
migrations; `kavrigo_app` is what the application connects as — not a superuser, not the table
owner, no `BYPASSRLS`. A superuser bypasses every RLS policy silently, so an app connecting as
one would pass the isolation tests while providing no isolation.

**PostgreSQL 18 changed its data mount.** It wants a single mount at `/var/lib/postgresql`, not
`/var/lib/postgresql/data`. Already fixed in the compose file; don't "correct" it back.

**Tooling not installed on the dev machine:** `uv`, `protoc`, `buf`, `gitleaks`. The Python
environment is a plain `.venv` built with `venv` + `pip`. `make setup` falls back to that
automatically. ADR 0014 chose `uv`; installing it is a pending human action.

**The network on that machine is slow** (~150–300 KB/s). Docker image pulls took 20–40 minutes;
NautilusTrader took ~2 minutes. Start long installs in the background and do other work.

---

## 5. Deferred work — read this before starting anything

Each item says which step it belongs to and why it was left. **None of these are bugs**; they
are scoped-out work with a reason.

### From step 3 — local stack

- **The API and worker Docker images have never been built.** `docker compose config` validates
  and Postgres/ClickHouse run, but `make up` end-to-end is unverified. Redpanda, Temporal and
  Valkey have never been started.
- **CI has never executed.** `.github/workflows/ci.yml` has six jobs including a Postgres +
  ClickHouse integration job. All written, none run — there is no remote.
- **Protobuf has never been generated.** `make proto` requires `protoc`, which is not installed,
  and there is no `buf.yaml`, so the CI `contracts` job degrades to a warning. The `.proto`
  files in `libs/data-contracts/` are hand-written and unvalidated by a compiler.
- **SBOM, Cosign signing and ECR push are deliberately absent** from CI rather than stubbed. A
  signing step that signs nothing gives false assurance (`MASTER_BUILD_SPEC.md` §24.4).

### From step 4 — control plane

- **Membership invite/remove endpoints are not built.** The `Permission` members exist
  (`MEMBER_INVITE`, `MEMBER_REMOVE`) and are covered by the role matrix; the routes are not.
- **Clerk configuration values are placeholders.** ADR 0021 built a standards-based JWKS
  verifier rather than a Clerk SDK integration, precisely so nothing was invented from memory.
  The issuer, JWKS URL, audience and claim names **must be confirmed against current Clerk
  documentation** before a real token is verified.
- **Token revocation is bounded by token lifetime**, not checked per request. Acceptable for
  paper mode; ADR 0021 flags it as needing revisiting before live execution.

### From step 5 — market ingestion

- **No live WebSocket transport.** This is the largest carry-over. Adapters, normalization,
  health monitoring and sinks are complete and tested against recorded frames and a scripted
  transport (`ScriptedTransport`). What is missing is a real socket with reconnect and
  keepalive. `python -m kavrigo_market_ingestion` says so explicitly rather than pretending to
  run.
- **Binance's connection lifetime and ping/pong interval are unverified.** The documentation
  pages reachable at the time did not state them. Keepalive was left configurable rather than
  hardcoding a number that could not be cited. **Verify against official docs before writing the
  transport.**
- **No Redpanda producer.** The `EventSink` protocol exists and `ClickHouseSink` implements it;
  a Kafka producer is a second implementation, not a redesign.
- **No loader that reads windows back out of ClickHouse.** The feature engine consumes an
  `InstrumentWindow` built in memory. Nothing yet turns stored rows into one. Step 7 needs this
  too — see below.

### From step 7 — backtest engine

- **No strategy layer.** The agent runtime that produces decisions is step 10, so a run today
  completes with **zero decisions** and flat metrics. This was reported honestly rather than
  wired with a placeholder strategy that would make the engine look further along than it is.
- **The deterministic BTC/ETH fixture run is deferred with it.** `AGENTS.md` step 7 asks for it;
  it needs a strategy to be meaningful.
- **Nautilus data and instrument wiring is not done.** `add_instrument()` and `add_data()` are
  never called. `build_engine()` configures the venue, account, fee, fill and latency models and
  is tested against a real engine — that boundary works; the data path does not exist yet.
- **No dataset builder.** `DatasetManifest` is a contract with leakage detection and a content
  hash. Nothing yet *constructs* one from ClickHouse rows.

### Cross-cutting

- **The data-licence matrix has zero confirmed rows** (`docs/product/data-license-matrix.md`).
  Both venues log `venue_license_unconfirmed` on startup — deliberately noisy. Public
  development use is one thing; display rights are a launch blocker (`MASTER_BUILD_SPEC.md`
  §8.3) with a long lead time.
- **The web app is not scaffolded.** ADR 0013 picked the stack; versions are to be resolved
  against current release notes at scaffold time, not from recollection.

---

## 6. Rules you must not break

From `AGENTS.md` § "Non-negotiable domain rules". These are enforced structurally in the code —
if a change makes one of them expressible, the change is wrong.

1. **A model output is never an exchange order.** Agents emit `AgentDecision`, a *proposal*.
2. **Only a deterministic risk evaluation can approve an `OrderIntent`.** `RiskEvaluation`
   cannot represent approving more than was requested — validation refuses it.
3. **Risk cannot be overridden by prompt, tool, or model output.**
4. **`UNKNOWN` and `NO_TRADE` are valid successful outcomes.** `AnalysisConfig` refuses
   `allow_abstain=False`.
5. **Data freshness is a risk input.** `StreamHealthMonitor` fails closed: a stream that never
   produced a message is `UNKNOWN`, not healthy.
6. **Money and quantity are exact decimals with units, never binary floats.** Enforced by
   `ExactDecimal`, by a pre-commit AST guard (`scripts/check_no_float_money.py`), and by sending
   decimals to ClickHouse as strings.
7. **Every high-impact mutation is idempotent.**
8. **Untrusted content is data, never instruction.** Web, news and MCP text is sanitized into
   structured evidence first (`docs/threat-model/untrusted-content.md`).
9. **Backtests are point-in-time.** Knowability is *arrival* time, not venue time. A leaky
   dataset is refused, not run.
10. **Every run references immutable versions.** There is deliberately no endpoint that changes
    an agent's behaviour in place; editing means creating a version.

**Two gates refuse at startup rather than branching at runtime.** Do not turn either into a
runtime `if`:

- `LIVE_TRADING_ENABLED=true` → the process fails to start (ADR 0001).
- `AUTH_PROVIDER=dev` outside `KAVRIGO_ENV=local` → the process fails to start (ADR 0021),
  because the dev provider accepts unsigned tokens.

**`kavrigo-execution-security/` must stay empty of code** until it is a separate,
access-restricted repository (ADR 0017). Nothing in this repo may hold an exchange credential
or construct a venue order.

**Architecture changes need an ADR** (`docs/adr/0000-template.md`), not a silent deviation.

---

## 7. Step 14 has a specific tooling instruction

The user asked, on 2026-09-07, that **all frontend/UI work use the `ui-ux-pro-max` skill**
(<https://github.com/nextlevelbuilder/ui-ux-pro-max-skill>).

Installing it is a human action, not an agent one:
`/plugin marketplace add nextlevelbuilder/ui-ux-pro-max-skill`, or
`npm install -g ui-ux-pro-max-cli && uipro init --ai claude`.

**Kavrigo's brand invariants override the skill's recommendations where they conflict.** The
skill proposes a design system from a product description; Kavrigo already has one, mandated in
`AGENTS.md` § "UI / brand design directive" and `MASTER_BUILD_SPEC.md` §30.8 — fixed tokens
(`ink-950 #090D12`, `brand-400 #5CC8FF`, `evidence-400 #4ED7B1`, `risk-400 #FF6B75`), Geist
Sans/Mono with tabular numerals, an "institutional trading terminal × modern AI lab" direction,
and explicit bans on neon, cyberpunk, heavy gradients and glow. The skill's headline styles —
glassmorphism, claymorphism, neumorphism — are therefore out of scope regardless of what it
suggests. Feed it Kavrigo's constraints as input; use its craft output.

Recorded in `kavrigo-platform/README.md` § "Design system".

---

## 8. How to verify you have not broken anything

```bash
make setup                        # venv + workspace packages (uv if present, else pip)
make check                        # ruff check + ruff format --check + mypy --strict + pytest
make up && make migrate           # local stack + database migrations
make test-integration             # RLS, immutability, API, ClickHouse (needs the stack)
```

Baseline at handoff time: **557 tests pass** (507 unit/property + 50 integration), ruff and
mypy `--strict` clean on 76 source files.

Integration tests **skip cleanly** when Postgres or ClickHouse is unreachable, so `make test`
works with nothing but Python. They must never require an external provider key — the CI
`quality` job re-runs the suite with every provider variable explicitly blanked to prove it.

---

## 9. Things that already cost an hour — do not rediscover them

- **Alembic must use `engine.begin()`, not `engine.connect()`.** SQLAlchemy 2.0 has no
  autocommit; with `connect()` the whole migration runs, reports success, and rolls back
  silently. Already fixed in `migrations/env.py`.
- **Alembic's version table needs its schema to exist first**, but the migration that creates
  the schema hasn't run yet. `env.py` issues `CREATE SCHEMA IF NOT EXISTS` to break the cycle.
- **The `ck` naming convention wraps explicitly-named check constraints.** Passing an
  already-prefixed name yields `ck_users_ck_users_...` and makes the migration disagree with the
  models on every autogenerate. Constraint names in migrations are bare.
- **Nautilus composes latency additively** — its reported insert latency is `base + insert`
  (verified against 1.231.0). Passing an already-summed total double-counts the base leg.
- **Coinbase's `match.side` is the *maker's* side**; Binance's `m` is "was the *buyer* the
  maker". Both are inverted by the adapters to yield the taker. Getting this wrong silently
  inverts CVD and every order-flow feature. Both are documented with source URLs and
  verification dates in the adapter modules.
- **Sorting events by timestamp alone is a partial order.** Python's sort is stable, so
  simultaneous events keep their input order and a replay picks a different "latest" event than
  the original run. `InstrumentWindow` sorts on a content-derived *total* order. Found by a
  property test.
- **Fixed-precision decimal is deterministic but not exact.** Three identical `ln(2)` log
  returns give a standard deviation around 1e-28, not 0. Compare against a tolerance.
- **ClickHouse TTL silently deletes backdated rows.** `market_trades` and `market_quotes` carry
  `TTL event_time + INTERVAL 90 DAY`. A row inserted with an `event_time` already past that is
  removed during an ordinary background merge — *after* the insert reported `written_rows`, at
  an unpredictable moment. This presented as intermittent data loss in the sink and took a while
  to pin down. **Test and fixture data must sit inside the retention window**; anchor timestamps
  to `now`, never to a fixed historical date. It also means a long-horizon backtest cannot read
  from these tables and must use frozen S3/Parquet datasets.
- **`market_candles` is a `ReplacingMergeTree` whose key excludes `provider`.** Two writers
  producing a bar at the same `(venue, instrument, interval, open_time)` are the same bar to the
  engine, and the newer `ingested_at` wins. Correct for a bar reissued as it forms; it means
  tests must use distinct `open_time` values or they silently overwrite each other.
- **Integration tests isolate by tagging rows, not by truncating tables.** Truncation isolates a
  test from its predecessors but not from a concurrent run — two pytest processes against one
  ClickHouse deleted each other's rows. Every assertion filters on a per-test `provider` tag, so
  concurrent runs are safe and nothing is deleted.
- **Do not write provider message shapes from memory.** Every venue format in this repo was
  fetched from official documentation and carries the URL and date. `AGENTS.md` requires it.

---

## 10. Your next task — step 8, the model gateway

From `AGENTS.md` step 8, implement:

- a **provider-neutral request/response contract** (`ModelGateway` protocol — the sketch is in
  `MASTER_BUILD_SPEC.md` §13.2);
- **cost, timeout and rate budgets** per workspace and per agent (§46);
- a **mock model provider** — the suite must pass with no API key;
- **tracing** hooks (Langfuse is ADR 0011, but it is *not* the audit ledger — §13.4);
- **structured output validation** — unvalidated model JSON must never enter the domain.

Constraints that shape the design:

- **Route by profile, not model name** (§13.5): `extract_fast`, `classify_fast`,
  `reason_balanced`, `reason_deep`, `embed`. Product behaviour must not be hard-coded to a
  current model name.
- **Record the resolved model identifier**, not just the profile. A routing fallback must never
  silently change what produced a reproducible result (ADR 0010). `ReproducibilityBundle` and
  `ModelCallRecord` already have fields for this — wire them.
- **No domain component may import a vendor SDK directly.** Same boundary discipline as
  `libs/nautilus-adapter`.
- **The gateway is the choke point that guarantees no credential ever enters model context**
  (§15.2). It must not be able to read one.
- `ModelCallRecord` in `kavrigo_domain/decision.py` is the existing contract for what a call
  produced — extend rather than duplicate it.

Suggested location: `kavrigo-engine/libs/model-gateway/` (`MASTER_BUILD_SPEC.md` §17 lists it),
registered in the root `pyproject.toml` workspace members, `[tool.uv.sources]`, `testpaths` and
ruff `known-first-party` — copy how `libs/backtest` was added.

---

## 11. What only the human can do

Do not attempt these; flag them.

- Install `uv`, `protoc`/`buf`, `gitleaks`.
- Create the GitHub org and the five repositories; push.
- Provision accounts: Clerk, Temporal Cloud, Redpanda Cloud, ClickHouse Cloud, Langfuse, AWS,
  Cloudflare, Stripe, a model provider.
- **Start commercial data-rights conversations with CoinGecko, CoinGlass and Dune.** Longest
  lead time of anything outstanding, and a hard launch blocker.
- Acquire `kavrigo.com` and obtain professional trademark clearance.
- Answer `MASTER_BUILD_SPEC.md` §64 — first jurisdiction, operating entity, permitted venues,
  product classification, KYC requirements, data residency, retention period.
