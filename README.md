# Kavrigo

**Build agents. Prove the edge. Enforce the risk.**

Kavrigo is an operating system for building, testing, observing, and governing AI trading
agents. Users create versioned `AgentSpec` configurations; agents produce **structured,
evidence-backed decisions**; a **deterministic risk engine outside the model** decides whether
an `OrderIntent` is permitted; execution is isolated behind a separate security boundary.

Authoritative documents, in reading order:

1. [`MASTER_BUILD_SPEC.md`](MASTER_BUILD_SPEC.md) — product/architecture specification.
2. [`AGENTS.md`](AGENTS.md) — engineering agent brief and non-negotiable domain rules.
3. [`docs/adr/`](docs/adr/) — architecture decision records.

## Launch mode

```text
LIVE_TRADING_ENABLED=false
DEFAULT_TRADING_MODE=paper
```

V1 is **research + paper, spot-only, non-custodial**. Live execution is a separately gated
release requiring legal, data-licensing, security, identity/jurisdiction and operational
approval (see `MASTER_BUILD_SPEC.md` §47). Nothing in this repository may create a shortcut
to real-money execution.

This software does not provide investment advice and makes no claim about future returns.
Backtest and paper results are simulations, not live results.

## Repository layout

This is a **bootstrap monorepo**. The five target repositories from `MASTER_BUILD_SPEC.md` §17
are mirrored as top-level directories until the GitHub organization exists. The split plan is
[`docs/repo-split-plan.md`](docs/repo-split-plan.md).

| Directory | Future repo | Contents |
|---|---|---|
| `kavrigo-platform/` | `kavrigo-platform` | Next.js web app, FastAPI control plane |
| `kavrigo-engine/` | `kavrigo-engine` | domain contracts, quant/data/agent services |
| `kavrigo-execution-security/` | `kavrigo-execution-security` | **boundary placeholder — no code yet** |
| `kavrigo-infra/` | `kavrigo-infra` | local stack, OpenTofu, Kubernetes, Argo CD |
| `kavrigo-research/` | `kavrigo-research` | notebooks, experiments, leakage audits |

## Quick start

Requires Docker, and [uv](https://docs.astral.sh/uv/) for Python.

```bash
make setup             # create the uv virtualenv and install workspace packages
make up                # start Postgres, Redpanda, ClickHouse, Temporal, Valkey, API, worker
make migrate           # apply database migrations
make test              # unit + property tests (no docker stack, no provider keys required)
make test-integration  # RLS, immutability and end-to-end API tests (needs `up` + `migrate`)
make check             # format check, lint, typecheck, tests
make down              # stop the local stack
```

The local stack is described in [`kavrigo-infra/local/README.md`](kavrigo-infra/local/README.md).
No external data provider, exchange credential, or model API key is required to run the tests.

## Current status

Phase 0 (foundation) of `MASTER_BUILD_SPEC.md` §59. Implemented so far:

- repository bootstrap, ADRs, threat-model template, CI skeleton, secret scanning;
- typed domain contracts (`kavrigo-engine/libs/domain`) and Protobuf stream contracts;
- local development stack;
- auth and tenant control plane: identity abstraction, workspaces and memberships, role and
  MFA-gated permissions, PostgreSQL row-level security, agent CRUD with immutable versioning,
  idempotent mutations and an append-only audit trail;
- market-data adapters for two venues, normalization, stream-health detection, replay, and the
  ingestion pipeline with a ClickHouse sink — a live WebSocket transport is not yet connected;
- a deterministic, versioned, point-in-time feature engine.

Not yet implemented: backtest engine, model gateway, news intelligence, agent runtime, risk
engine, paper broker, Temporal workflows, web UI.
