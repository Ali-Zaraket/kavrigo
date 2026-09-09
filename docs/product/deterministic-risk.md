# Deterministic risk — step 11

`kavrigo-risk` implements ADR 0004 within the local boundary recorded in
[ADR 0025](../adr/0025-local-deterministic-risk.md). It evaluates requests and can hand a permit
to a local paper consumer. It does not submit an order, fill a position or connect to a venue.

## Inputs and ownership

- `RiskRegistration`: an authorized immutable AgentVersion, hashed RiskPolicies, explicit
  execution assumptions, freshness windows, notional increment and network mappings.
- `RiskControls`: trusted supervisor observations for one workspace/account, monotone version,
  availability/calendar state, scoped kills, agent revocations and a fencing lease.
- `PortfolioSnapshot`: reconciled USD spot cash/positions at a frozen generation. Existing open
  orders, reserved cash, missing marks, short quantities and inconsistent totals are refused.
- `RiskRequest`: canonical OrderIntent, server-bound AgentDecision, runtime Allocation, frozen
  MarketSnapshot/evidence and a normalized book/liquidity observation. The coordinator owns
  these inputs; a model cannot supply policy, account identity or authorization.

Liquidity is a trusted coordinator observation with operator-defined semantics, not a new
provider field. Fee/slippage values are explicit versioned local assumptions. Verify real
provider semantics and rights before wiring a collector. Source quotes are untrusted facts;
their content never changes risk settings. The model's estimated cost is not used as authority.

## Evaluation

Global, workspace and agent policies are mandatory. Every registered policy applies to the
account in this conservative slice; all hierarchy levels can restrict an approval. Percentages
use portfolio equity after reserved/prospective fees. Cross-venue holdings share an asset cap.
The most restrictive limit wins; `binding_scope` identifies a rule blocking the next size step.

Freshness adds time since the snapshot's `as_of` to the recorded age of each family. Missing,
stale, gapped, unhealthy, future or low-quality data fails closed. Evidence must be present,
available by snapshot time, enabled by the AgentSpec, sufficiently rated and free of recorded
injection signals. Supporting and required contradicting evidence must be distinct.

Costs include configured fee/slippage and observed spread for the economic margin. Buy sizing
reserves notional plus fees and rechecks gross, every asset, every network, position count and
loss/drawdown limits after costs. Book depth bounds the request. Sell sizing reserves held
quantity and fee cash; unfilled buys cannot be sold and unfilled sales cannot finance buys.
REDUCE/CLOSE may exit during loss/event breakers without a positive predicted return. Kill,
freshness, known-state, lease, holdings and fee constraints still apply to exits.

Amounts use 12-place fixed-point integers internally and Decimal contracts externally. Values
outside the supported range/precision, including unrepresentable account products, reject.
The configured increment rounds sizing down; cash reservations round fees up. Examples and
test thresholds are synthetic configuration, not investment recommendations.

## Handoff and replay

Create one `LocalRiskSession(environment="local", ...)` per frozen account generation. Register
all its eligible agents together. `evaluate(request)` returns a `RiskRecord`, whose evaluation
is APPROVED, APPROVED_RESIZED or REJECTED and whose hashes bind the actual inputs, policies,
portfolio, controls and prior reservations. Reusing the same key and exact request returns
that record. Key/intent collisions with different content and a second intent for a decision
are refused. Concurrent requests share the same lock and reservations.

Call `handoff(workspace_id=..., order_intent_id=..., fencing_token=...)` to obtain at most one
`PaperRiskPermit`. It rechecks freshness and supervisor state, including revocation/kill and
lease validity. The permit contains `ApprovedOrderIntent`, `max_quantity` and `max_cash_debit`.
These ceilings are jointly binding on the local paper broker. The permit also carries its
issuer's immutable `RiskExecutionPolicy` (required internal field added in step 12). A type or hash does not
authenticate its issuer across a service boundary.

Step 12 records the actual issued permit and adds `execution_allowed()` and
`execution_guard()`. Only an already-issued command can pass the recheck. The guard holds
the risk lock through a local paper commit, serializing it with supervisor changes and new
reservations. Rechecking uses the frozen inputs at their original freshness deadlines.
It does not issue another permit, refresh a portfolio or release any reservation.

If the caller crashes after handoff, risk cannot know whether the consumer received it. It
retains the reservation and never issues a second permit. Expiry also retains reservations.
Capacity exhaustion refuses new work. There is no release/reset shortcut or portfolio refresh;
reconciliation with the future broker is needed before resources may safely be reused.

## Audit and visibility

`audit_events` exposes detached copies of bounded append-only evaluation, control-update and
handoff records, linked by artifact/control hashes and sequence. Replaying a lookup does not
duplicate an authoritative event. Audit capacity exhaustion prevents further high-impact
mutations. This in-memory history needs durable persistence before deployment.

OTel records `kavrigo.risk.evaluations`, `kavrigo.risk.reasons`, `kavrigo.risk.handoffs` and
`risk.evaluate` spans. Structured logs contain closed outcomes/reasons, without evidence text,
model rationale, workspace IDs, amounts or exception bodies. No hosted exporter is configured.

## Remaining integration

Step 12's [local paper broker](paper-broker.md) now owns canonical orders/fills/cash/positions,
acknowledgements and replay reconciliation within one batch generation. Step 13 owns durable
workflow and serialized account ownership. Process restarts and safe reservation release need
those deployed stores. HTTP authorization/RLS, durable
audit/outbox, risk stream publishing, provider observation authentication and restricted review
are still required. No production or live execution readiness is implied by local tests.
