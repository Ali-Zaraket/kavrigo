# Paper broker — step 12

`kavrigo-paper` implements the local simulation boundary in
[ADR 0026](../adr/0026-local-paper-broker.md). It produces canonical Order, Fill and
PortfolioSnapshot objects from actual local risk issuance and synthetic market observations.
All amounts and results are paper/backtest simulations. There is no provider connection or UI.

## Ownership and contracts

`LocalPaperVenue` owns one workspace/account and frozen initial portfolio generation. Supply
the same actual `LocalRiskSession` used for evaluation. `submit()` takes workspace, intent ID
and fencing token; it obtains the permit itself. A caller cannot submit an approval or Fill.
The permit includes its issuer's immutable execution policy, exact quantity/cash bounds,
approved notional and input/policy hashes. Repeated committed intent IDs return the existing
order, including after expiry or a control change; this lookup never executes again.

`LocalPaperBroker` holds a separate projection. Its `state` contains canonical orders,
portfolio, integer-derived cost basis, cumulative fees and per-instrument mark timestamps.
`PaperConfig` freezes version, latency, market age, instruments, tick/lot increments and
minimum notional. `PaperBook` is an internal synthetic full-depth contract, with event time,
received time, sequence and explicit full-resync assertion. It is not a provider wire schema.

`PaperReplay` stores the initial account/config and up to 1,000 commands with sequence,
previous-entry hash, an entry hash covering the command, and resulting state hash. The first entry binds the header.
Snapshots and complete replay artifacts are limited to 10 MB. Commits validate the prospective
state and journal size before changing authority; capacity never evicts idempotency records.
All inputs and returned artifacts are detached through serialization and validation.
Imported replay bundles are read-only historical artifacts, never executable authorizations.

## Matching and accounting

Only USD spot MARKET/IOC paper/backtest orders are supported. Initial accounts must be known,
reconciled, free of outstanding orders/reservations, and have consistent marks and cost basis.
Money and quantity use authoritative integers at 12 fractional places, with input magnitude
at most 10^18. Tick times lot and initial valuation products must be exactly representable.

A book can match only after submission plus configured latency in both event and received
time. Out-of-order, conflicting duplicate, future or unaligned observations cannot mutate the
ledger. A sequence gap or stale observation blocks matching; a gap needs an explicit full
resynchronization. A fresh update for ETH cannot make an old BTC position mark fresh.

Before matching, risk rechecks the issued command's frozen inputs, current controls, lease,
expiry and retained reservations. The local risk lock remains held through the venue commit,
serializing supervisor changes with fills. Frozen evidence/market liquidity observations
still have their original freshness deadlines; a new synthetic book does not refresh them.
The simulator separately checks its book health and execution-policy market age.

The simulator crosses the observed book, applies configured adverse slippage and rounds price
outward to the tick. Orders consume finite depth in submission order. Each fill respects
cumulative approved notional, quantity and cash debit; fees round upward to one fixed-point
unit. The order becomes FILLED when its approved, lot-rounded quantity is satisfied. An IOC
partial fill becomes CANCELLED with `ioc_remainder_cancelled`; the immutable fills remain.
Below-minimum submissions become REJECTED. Expiry, coordinator cancellation and failed risk
rechecks create no fill. Unknown broker acknowledgements are represented as UNKNOWN views.

Buys debit gross plus fees and add exact gross cost basis. Sales remove proportional integer
basis, rounding down and retaining any remainder on the remaining position; full exit removes
all remaining basis. Fees are expensed immediately. Realized daily P&L follows UTC dates;
unrealized P&L uses observed bid marks. Rounded average prices are display projections and
never accounting inputs. Cash plus marked positions equals equity. Simulator reservations
settle on terminal orders; the original risk session retains its conservative reservations.

## Recovery and limits

An acknowledgement can be deliberately lost for fault tests with `acknowledge=False`. The
simulator may already have committed. The broker marks its view unreconciled and refuses
submissions. A later ordinary acknowledgement cannot erase the uncertainty: call `reconcile()`
to replay the authoritative journal, validate its state and discover missed fill IDs. A new
broker over the **same still-live venue object** also recovers without resubmission. Diagnostic
failure after commit preserves dedupe and can be reconciled the same way.

This is a **single-generation batch**. Submit the generation's approvals before the first
eligible matching attempt. After that attempt, new orders are refused. There is no risk
reservation reset/release, portfolio reseed, serialized venue restore or continuous trading
loop. Failure between risk handoff and the first journal commit retains the risk hold and
may strand that command; it never reissues a permit. Do not recreate the risk session to
work around it. Transactional PostgreSQL receipts/outbox, account ownership and workflow
recovery are required before process-restart durability or continuous operation (step 13).

Python object references, locks and hashes are local controls, not service authentication.
There is no HTTP route, RLS-backed broker store, event publisher or hosted worker in this slice.
Nautilus strategy/data wiring and a meaningful benchmarked BTC/ETH backtest remain separate.

## Verification and visibility

Run `python -m pytest kavrigo-engine/services/paper-broker/tests` in the installed workspace.
Fixtures cover exact accounting, partial fills, shared depth, rejected/model-unavailable
decisions, freshness/gaps, duplicate concurrency, control changes during matching, lost
acknowledgements, unknown fills, replay tampering, size exhaustion and ambient decimal context.
The runtime integration uses the mock ModelGateway through runtime, risk, broker and replay;
the property test checks approval ceilings, cash/equity identities and replay equivalence.

`paper.commit` spans and `kavrigo.paper.commands`, `kavrigo.paper.fills`,
`kavrigo.paper.reconciliations` counters accompany metadata-only structured logs. Diagnostic
fields are closed command kinds and counts, without financial amounts, workspace IDs,
evidence or exception bodies. The financial journal is restricted application data; it is
never a telemetry payload. Hosted export and independent security review remain pending.
