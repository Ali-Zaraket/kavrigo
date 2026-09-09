# ADR 0026: Deterministic local paper ledger and reconciled projections

- **Status:** Accepted for local simulation; independent security review pending
- **Date:** 2026-09-09
- **Spec reference:** AGENTS.md step 12; MASTER_BUILD_SPEC.md §§12.4, 15.4–15.5, 37, 50; ADR 0025

## Context and options

Risk produces one-time local permits but there is no broker, fill accounting or authoritative
paper state. Reconstructing risk from stale positions or releasing reservations after a timeout
would allow duplicate execution. PostgreSQL remains the intended authoritative service store;
Temporal/account ownership and deployed risk are not yet wired.

Options are a deployed database broker immediately, a stateless fill calculator, or a bounded
local simulator with an authoritative journal and a separate reconciled projection. Choose the
last option for this slice. A stateless calculator cannot test unknown acknowledgements or
reconciliation; deployment now would imply recovery and authorization that do not exist yet.

## Decision

Add `services/paper-broker`. One local simulated venue owns one workspace/account and initial
portfolio generation. It receives an actual LocalRiskSession and obtains permits directly;
the public submission API accepts identifiers, never caller-constructed approvals or fills.
Risk records its issued permit and supplies its versioned execution assumptions. It rechecks
the issued command before simulated matching, including current controls, expiry and fencing.
Hold the local risk lock through the venue commit so supervisor updates cannot interleave
between that check and the fill. This mutex is not a substitute for deployed account fencing.

Versioned synthetic full-book events drive deterministic USD spot MARKET/IOC fills. Apply
configured latency, adverse slippage, tick/lot increments, finite depth and taker fees. Orders
share consumed depth in submission order. A partial IOC fill cancels its remainder. Duplicate
events/commands are idempotent; conflicting reuse and out-of-order events fail closed. A feed
gap blocks matching until a declared full resynchronization. Expiry/kill/cancellation do not
create fills. The simulator has no socket, secret, venue adapter or exchange command.

Use the risk slice's 12-place integer arithmetic for money/quantity. Tick times lot must be
exactly representable. Fees round upward; fill sizing respects cumulative approved notional,
quantity and cash ceilings. Positions retain integer cost basis; partial sales allocate basis
proportionally, rounding down and leaving the remainder on the remaining position. Full exit
removes the remaining basis exactly. Fees are expensed when incurred. Rounded average prices
are projections, never inputs to accounting. Long positions are marked at the observed bid.
Initial valuation/P&L must be consistent. Track each held instrument's mark time independently;
an update for another instrument cannot hide a stale mark.

The simulator commits an input and resulting state hash to a bounded hash-linked journal
before returning an acknowledgement. Replaying starts with the frozen initial account/config;
it validates sequence/hash continuity and reproduces orders, fills, cash, basis, fees and P&L.
The first entry binds the initial account/config header. Limit journals to 1,000 commands and
artifacts to 10 MB, validating prospective state and journal size before each commit.
A disconnected broker view is explicitly unreconciled, retains uncertainty and cannot authorize
new submissions. Reconciliation reads the authoritative simulator journal, discovers missed
fills and updates its projection. A reconstructed broker view over the same simulator can
recover a lost acknowledgement without submitting again.

This remains a single-generation batch: submit approved commands before matching begins.
After the first eligible matching attempt, refuse new orders. Risk reservations remain retained;
there is no reset/release/reseed API. This permits honest partial-fill/reconnect/replay tests
without claiming continuous operation or process-restart durability. Step 13 must replace the
local journal and ownership with transactional PostgreSQL state, durable idempotency/outbox,
safe risk generation transitions and workflow recovery before continuous operation.

## Security, operation and rollback

Non-local startup is refused. Callers/configuration and the in-process risk/venue objects are
trusted; Python privacy and content hashes are not cross-service authentication. Replay exports
are historical artifacts, not executable authorizations. Every operation checks workspace and
account scope. No changes to execution-security or live gates. OTel/logging contain closed
outcomes/counts only; the local journal carries restricted financial data and is not exported
by telemetry. Capacity fails closed without evicting dedupe or reservation state.

Rollback stops this local simulation. Never resume an old portfolio as a fresh account if any
downstream receipt may exist. No migration or stream schema is added. A real authenticated
API/RLS boundary, persistent audit, account ownership, provider rights and independent security
review remain required. No meaningful Nautilus strategy integration or production claim follows.

## Evidence

Existing canonical Order/Fill/PortfolioSnapshot and risk contracts were inspected first.
[Python Decimal](https://docs.python.org/3.13/library/decimal.html) and
[Pydantic models](https://docs.pydantic.dev/latest/concepts/models/) were checked on 2026-09-09:
ambient Decimal arithmetic and shallow frozen containers require explicit boundaries. Inputs
and returned artifacts are serialized/revalidated; authoritative arithmetic uses integers.
Synthetic book fields are an internal simulation contract, not an invented provider schema.
