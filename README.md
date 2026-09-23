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
make test-integration  # configure a separate migrated test DB first; see local stack README
make check             # format check, lint, typecheck, tests
make down              # stop the local stack
```

The local stack is described in [`kavrigo-infra/local/README.md`](kavrigo-infra/local/README.md).
No external data provider, exchange credential, or model API key is required to run the tests.

## Current status

Local slices cover steps 1-15 of `AGENTS.md`: Studio paper drafts, a synthetic execution-disabled
rehearsal, durable Temporal receipts, deterministic risk and paper accounting, local observability,
and immutable policy candidates with independent review recommendations. A public market-data
WebSocket transport is available for brief, explicitly enabled local samples that discard feed
data. The end-to-end product milestone still needs licensed real-data persistence, meaningful
catalog-backed agent/risk replay in Nautilus, approval gates, and an approved paper launch. A
bounded synthetic reference strategy now verifies Nautilus decisions, fills, costs and benchmark
metrics but remains explicitly non-promotable.

See [`PROGRESS.md`](PROGRESS.md) for current verification counts and remaining work, and
[durable workflow operations](docs/product/durable-workflows.md) for recovery limits.
Independent security review, hosted deployment and continuous production operation remain pending.
