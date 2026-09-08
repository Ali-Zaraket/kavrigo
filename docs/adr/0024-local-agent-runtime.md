# ADR 0024: Bounded local runtime and unapproved portfolio allocations

- **Status:** Accepted
- **Date:** 2026-09-08
- **Deciders:** Principal engineering agent
- **Spec reference:** `MASTER_BUILD_SPEC.md` §§6, 10, 13, 25, 38, 46; build step 10

## Context

The gateway and news slice now provide typed local model outputs and attributable evidence.
Step 10 must bind those to immutable agent/snapshot context, search for contradictions and
allocate competing proposals without granting any execution authority. The API's scaffold
prompt hash does not match the registered gateway prompt, including its data boundary.

## Options considered

1. Give an agent tool loop mutable reads and portfolio/exchange tools. Violates the frozen
   decision-cycle boundary and exceeds the available verified mock provider capability.
2. Use one model call for all assets and portfolio sizing. Makes deterministic ownership and
   per-decision provenance harder to enforce and can double-count correlated proposals.
3. Deterministic scanner, frozen network interface, one typed proposal per candidate and
   deterministic allocation, with explicit local process budgets. Selected for this slice.

## Evidence

Official sources verified 2026-09-08:

- [Python decimal](https://docs.python.org/3.13/library/decimal.html#decimal.Decimal.normalize)
  states that normalize applies rounding before reducing the representation. A precision-3
  regression reproduces a hash collision/rounding problem in the existing canonical hash helper.
  Fixed-point formatting followed by removal of insignificant zeros avoids that arithmetic.
- [Python asyncio timeouts](https://docs.python.org/3.13/library/asyncio-task.html#timeouts)
  documents cooperative cancellation and deadline behavior. The whole cycle has a deadline in
  addition to the gateway's per-call limit. This is not process isolation of a blocking SDK.
- Existing step 8 Pydantic and OTel interfaces are reused. No new vendor API or SDK is assumed.

## Decision

Add `services/agent-runtime`. Trusted service code registers immutable `AgentVersion` and
`RuntimePolicy`, the gateway, and a read-only provider of already frozen network contexts.
Snapshot/feature/config hashes, workspace/mode, portfolio accounting, timestamps and enabled
evidence packs are validated before model calls. Missing marks are unknown exposure, not zero.

The scanner uses explicitly configured absolute thresholds over versioned features. For each
hit, interest is `abs(value) / (abs(value) + threshold)`; the maximum hit ranks the candidate.
Stable instrument tie breaks, candidate TTL and candidate/call/day/interval/capacity limits bound
work. One requested horizon must belong to the immutable spec; scheduling horizons/triggers is
the workflow layer's responsibility. `max_tool_calls` does not grant a tool: this slice has none.

Each candidate gets a closed `DecisionProposal` through the gateway. The model must inspect
the frozen corpus for contradictory evidence even if the feed has not pre-labelled any.
Trade proposals require valid, distinct supporting/contradicting references as configured,
the requested horizon/currency and a non-negative cost estimate. Reference checks prove that
material was supplied, not the truth of a claim or the semantic correctness of a contradiction.
Missing evidence/context, expired data, unavailable models and invalid output abstain or refuse.

The runtime binds authoritative decision/workspace/version/snapshot/instrument/time and actual
model records. The gateway gains a read-only, authorized terminal-record lookup so cancellation
can retain unknown spend without redispatching a provider. Interrupted cycles are terminal under
their idempotency key; no incomplete cycle receives portfolio allocation.

Portfolio allocation uses USD-quoted spot assets only, configured overlap groups, existing
positions, available cash, new-allocation/group budgets and an explicit fee buffer. Stable
ranking chooses competing proposals; allocations can only reduce requested notional. Allocation
rounds down to 12 decimal places, an internal accounting precision rather than a venue tick.
Unfilled sales never fund buys. Pending orders or unknown exposure refuse allocation. Actual
correlation estimation, FX conversion and live accounting are not inferred from configuration.

The output is inert `PortfolioDecision` / `Allocation`, never an `OrderIntent`, risk approval,
order or fill. Step 11 owns risk and creation of approved intents; step 12 owns paper execution.

Move shared default analysis text into a domain prompt artifact. Newly created API versions
pin prompt v2 through the gateway's common `prompt_text_hash`, matching the runtime. Prior
immutable versions are not rewritten; the runtime rejects their incompatible scaffold hash.

## Security and compliance impact

Local-only construction; no model/provider secret, external fetcher, arbitrary code, SDK import
or exchange write tool. Caller authentication and authorization remain a service/control-plane
responsibility; registrations are not taken from model JSON. Hashes provide integrity, not
authentication of records from an arbitrary caller. Evidence and rationale remain untrusted
text and must be escaped by the future UI. Deterministic risk remains an independent release
step. Existing LIVE_TRADING_ENABLED and dev-auth startup refusals are unchanged.

## Operational impact

Budgets/idempotency are atomic in one process, bounded without eviction, and lost on restart.
No multi-process scheduling, persistent decision ledger, hosted exporter or deployed agent
worker is claimed. OTel spans/counters and structured status logs contain outcome metadata,
not source text/rationale/exception bodies. Actual gateway records include cancelled attempts.

The default local gateway remains scripted. Backtest registration requires a model pin; the
fixture runtime alone is not a Nautilus strategy or a guarantee that a later network model
has no historical knowledge. Recorded-model artifact loading and strategy wiring remain part
of the pending end-to-end backtest path.

## Migration and rollback

Additive service and API dependency on the existing gateway artifact hash helper. No database
migration or stored version update. A new API-created agent version uses prompt v2; creating
that version is the explicit migration from scaffold v1. Rolling back restores v1 for future
versions only, not existing records.

Canonical Decimal hashing now preserves all digits independent of ambient precision and
canonicalizes signed zero. Old hashes that depended on prior rounding/signed-zero formatting
may no longer verify. Do not rewrite historical hashes in place: retain original artifacts for
inspection and generate new versioned snapshots/configurations for new runtime work. A hash
mismatch refuses execution rather than silently accepting inconsistent provenance.

## Consequences

The paper path can produce evidence-backed structured proposals and conservative allocations
with testable uncertainty and failure behavior. Durable orchestration, empirical correlation,
network collectors, production model tools and the actual risk/execution chain remain separate.
