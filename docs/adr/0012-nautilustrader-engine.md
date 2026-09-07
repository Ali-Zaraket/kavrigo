# ADR 0012: NautilusTrader (stable) behind internal adapter interfaces

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §12.1

## Context

Realistic simulation — fees, spread, partial fills, queue position, latency, order rejection — is years of work to build credibly, and backtest/live semantic parity is the single largest source of false confidence in trading platforms.

## Options considered

1. **Build a bespoke event-driven backtester** — full control, very high cost, high risk of optimistic fills.
2. **NautilusTrader stable release, wrapped by our own domain contracts.**
3. **VectorBT or a vectorised backtester** — fast research iteration, poor live-parity semantics.

## Decision

Option 2, pinned to a stable release. Nightly or release-candidate features are not used in production without an explicit ADR. Our domain contracts stay independent of the engine so it can be replaced. LGPLv3 obligations must be reviewed with counsel before distribution decisions.

## Security and compliance impact

Licence review is a launch prerequisite. The engine executes strategy code in our own services only; user-supplied code is out of scope for V1 (ADR 0018).

## Consequences

Easier: credible fills and research/live parity. Harder: an upstream dependency on the hot path, and a licence obligation to track.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
