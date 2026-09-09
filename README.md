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

For continuing work, start with [`PROGRESS.md`](PROGRESS.md), then the detailed
[`HANDOFF.md`](HANDOFF.md). [`MACHINE_HANDOFF.md`](MACHINE_HANDOFF.md) explains how to clone
and set up another machine; [`HANDOFF_PROMPT.md`](HANDOFF_PROMPT.md) supplies the next-task prompt.

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

Requires Git, Make, Python 3.13 and Docker with Compose v2.
[uv](https://docs.astral.sh/uv/) is preferred; `make setup` falls back to venv/pip if unavailable.

```bash
make setup             # create the virtualenv and install workspace packages
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

Committed slices cover steps 1–12 of `AGENTS.md`, through the local/mock model gateway,
synthetic news intelligence, agent runtime, deterministic risk and paper broker. The broker
models exact IOC fills, fees, cash/positions and P&L, with idempotent receipts and journal
reconciliation. It is a bounded local batch; process-restart durability, continuous operation,
Temporal workflows and the product UI remain pending. The end-to-end paper milestone is not complete.
The backtest engine still needs strategy/data wiring and a meaningful BTC/ETH fixture run.

The destination checkpoint passed 847 tests with zero skips, plus a dedicated run of all 50
database integrations. Lint, strict typing, image rebuilds and migrations passed. Step 13 is
next; independent risk/security review and durable operation remain pending. See
[`PROGRESS.md`](PROGRESS.md) for commit references, recorded validation and remaining work.
