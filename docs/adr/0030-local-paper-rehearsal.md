# ADR 0030: Explicit synthetic paper rehearsal before policy activation

Status: accepted for local bootstrap, 2026-09-18.

## Context

MASTER_BUILD_SPEC §28 calls for a paper launch from Studio, while the current product has
immutable draft versions and read-only run inspection but no policy provisioning, approved
versions, or connected market snapshot service. Treating a draft's arbitrary policy ID as an
approved policy would breach the deterministic-risk boundary. An ordinary paper run cannot be
offered yet. Users nevertheless need a real, inspectable end-to-end workflow invocation.

## Options and decision

We considered exposing the existing `AgentJob` as a client-supplied payload, auto-approving
draft policy IDs, or running a local synthetic rehearsal. The first two let client text supply
trusted market/risk artifacts or silently grant approval. We chose a strictly local rehearsal
that constructs all frozen inputs server-side from the stored immutable version. It uses a
separate paper account with a global kill, failed connectivity, zero exposure limits, and
the worker's abstaining mock model. The draft is not promoted. Neither model output nor an
API request can cause an order in this rehearsal.

`RUN_START` and workspace membership gate the endpoint. A mandatory idempotency key derives
one run ID per workspace; the account, run and outbox event commit in one transaction. Retrying
the key reuses the original frozen input or rejects a changed version. The runtime key is a
deterministic contract-safe derivative of the client key, so browser UUID keys remain valid.
The API dispatches only
that run through the existing Temporal path, then marks the outbox delivered. If Temporal is
unavailable, the run remains queued and a same-key request retries dispatch. The local worker's
optional static workspace scanner remains an operator fallback; automatic cross-tenant outbox
discovery is not added because it would require a new privileged identity design.

## Safety, operations and limits

The UI and inspection API label these records `synthetic_rehearsal`, never market or backtest
results. Synthetic features, evidence and book values have no provider license or predictive
claim. The runtime's code-image digest remains an explicit all-zero local placeholder; these
runs are **not publishable reproducible research** and cannot be promoted. The account has no
execution-capable control state even if a future mock proposes an order. No exchange credential,
live endpoint, real provider, or arbitrary user code is involved.

The control-plane API now depends on the existing workflow package for typed run creation and
dispatch. This adds local Python image weight; a later service split may move dispatch to a
dedicated worker API. The endpoint is refused outside `KAVRIGO_ENV=local` and paper mode.
Hosted authentication, approved policy lifecycle, real point-in-time market data, operational
outbox recovery, and order-capable paper activation remain separate work.

Rollback removes the route and Studio control while retaining immutable synthetic receipts for
audit. No migration or authoritative ledger rewrite is required.

Official Temporal Python SDK reference checked 2026-09-18:
[Client.start_workflow](https://python.temporal.io/temporalio.client.Client.html#start_workflow)
and [Workflow ID reuse](https://python.temporal.io/temporalio.common.WorkflowIDReusePolicy.html).
