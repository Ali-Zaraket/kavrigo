# ADR 0025: Local deterministic risk reservations and paper handoff

- **Status:** Accepted
- **Date:** 2026-09-09
- **Deciders:** Engineering; human security review remains required before deployment
- **Spec reference:** `MASTER_BUILD_SPEC.md` §6.6, §11, §15.4–15.5, §25, §37; ADR 0004

## Context

Step 10 produces validated decisions and inert allocations. The canonical risk contracts exist,
but no evaluator enforces them. There is no paper broker or authoritative reservation/lease
store yet. Approving each request against the same unchanged portfolio would overspend cash
and exposure. A time-valid evaluation also becomes unsafe if data, controls or a lease expire
before handoff. Python type construction alone cannot authenticate an approval.

## Options considered

1. A pure evaluator alone: useful for replay, but cannot coordinate concurrent approvals.
2. Immediately deploy risk with a new account ledger: duplicates the pending paper broker's
   authoritative state and invents reconciliation semantics before that ledger exists.
3. A pure evaluator behind a bounded local account session, with reservations retained until
   the future broker supplies durable reconciliation. Refuse non-local startup.

## Evidence

Official documentation checked on 2026-09-08/09:

- [Pydantic model validation and faux immutability](https://docs.pydantic.dev/latest/concepts/models/):
  frozen models can contain mutable containers; copies are not a validation boundary.
- [Python 3.13 Decimal](https://docs.python.org/3.13/library/decimal.html): arithmetic uses an
  active precision/rounding context; `as_integer_ratio()` preserves the exact input value.
- [Hypothesis strategies](https://hypothesis.readthedocs.io/en/latest/reference/strategies.html):
  generated sequences exercise accumulated reservations, stale data, duplicates and rejection.
- Existing `RiskPolicy`, `OrderIntent`, `ApprovedOrderIntent`, runtime allocation and evidence
  contracts were inspected before implementation. No venue/provider wire API was introduced.

Property testing found a cross-asset counterexample: reserving fees on an ETH buy reduced
equity enough to exceed the concentration limit on a prior BTC approval. Sizing now checks all
asset/network exposures after new fees; the minimized case is retained as an explicit example.

## Decision

Use option 3 in `services/risk-engine`. One `LocalRiskSession` owns one workspace/account and
frozen portfolio generation. It revalidates detached inputs, loads immutable registrations,
evaluates deterministic policies, and atomically records resource reservations and local audit
events. Replays return the original record; changed key/intent/decision reuse is refused.

Use integer fixed point with 12 fractional places and input magnitude at most 10^18. Monetary
contracts remain Decimal with units. Account valuation products must be exactly representable.
Unsupported precision fails closed. An integer search finds the largest permitted notional
increment; cost reservations round upward, approvals round downward. This preserves the
existing shared context for analytical features without depending on it for risk arithmetic.

The slice accepts USD spot MARKET/IOC requests in paper or backtest mode. Global, workspace
and agent policies are mandatory; all supplied hierarchy levels apply. Upper policies must
agree across registered agents. Positions lack agent attribution, so the account applies the
union of every registered policy conservatively (maximum 16 distinct policies). Asset exposure
aggregates across venues; network groups are explicit operator configuration. Full scope/lot
attribution remains a broker/control-plane task.

Check governance, proposal/allocation binding, evidence eligibility, freshness as of evaluation,
portfolio consistency, reconciliation, market spread/depth, cost margin, exposure, cash,
position count, loss/drawdown, calendar availability and kill controls. Buy sizing also checks
all existing concentrations after prospective fees. Daily-loss percentage uses current frozen
equity as its denominator; reservations include a conservative fee loss. Explicit REDUCE/CLOSE
actions can reduce holdings during loss/event breakers and do not require predicted profit;
all integrity and kill controls still apply. Scheduled event windows reject new risk, including
when a policy requests a partial reduction.

Handoff rechecks time-dependent policy and the supervisor's fencing token. It returns one
`PaperRiskPermit`, containing the canonical approval and hard quantity/cash ceilings. It marks
the handoff consumed before returning. A retry cannot get another permit. Expiry, handoff,
unknown acknowledgement, telemetry failure, and capacity pressure never release reservations.
There is no reset/release API. Controls advance monotonically and support revocation.

## Security and compliance impact

Risk receives no model tool interface, secret, credential lookup or venue command. No code is
added to the execution-security boundary and existing startup safety gates remain in force.
Records and hashes provide local integrity/provenance, not cross-process authentication.
Callers must supply authorized versions, normalized data and supervisor state. This package
has no public endpoint. The future broker must authenticate risk issuance and enforce the
permit's quantity, cash, expiry, client-id and fencing limits at submission.

## Operational impact

No durable or distributed ownership, database reservation store, account-state refresh, order
submission, reconciliation or event publisher is implemented here. State is lost on restart;
never run competing sessions for an account or deploy this local ledger. Capacity refuses work
instead of evicting reservations. Local audit events are bounded and append-only; metadata-only
OTel counters/spans and logs are diagnostic, not an audit store. See the risk threat model.

## Migration and rollback

This adds an internal package and reason codes without a database migration or stream change.
Step 12 must connect a canonical paper ledger and safely transfer/reconcile outstanding
reservations; step 13 must provide durable serialized account ownership and crash recovery.
Authenticated service APIs, persistent audit/outbox and permissioned policy updates precede any
deployed risk service. Rollback stops the local session; do not reconstruct it from an old
portfolio and replay commands when a downstream consumer might already have received permits.

## Consequences

The mock runtime can now reach a tested, deterministic risk approval boundary. The complete
paper product, continuous operation, meaningful Nautilus backtest and live readiness remain
unfinished. Conservative account-wide policies, precision restrictions and retained reservations
limit throughput and flexibility intentionally until the authoritative broker is built.
