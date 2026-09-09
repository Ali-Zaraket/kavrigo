# Local risk issuance → paper simulator → broker projection

Status: local author review; independent security review pending. Requirement: step 12,
MASTER_BUILD_SPEC §§12.4, 15.4–15.5, 37 and 50. Decision: [ADR 0026](../adr/0026-local-paper-broker.md).

## Assets and trusted boundaries

Protect cash, positions, cost basis, approval ceilings, receipt identity and recovery history.
The trusted local coordinator constructs the initial account, instrument/cost configuration,
risk registration, supervisor state and synthetic books. Models and news cannot invoke the
broker or choose those inputs. Workspace is checked on every venue operation. Risk additionally
binds account, portfolio generation, registered agent, evidence and policy before issuance.

The venue is authoritative only within its current process; the broker is a disposable view.
There is no external API/authentication, cross-process lock, persistent ledger or live venue.
Content hashes detect accidental or partial artifact edits, not an attacker who rewrites and
rehashes an entire bundle. Historical replay is never accepted as execution authorization.

## Threats and controls

| Threat | Control and verification |
|---|---|
| Fabricated model approval or arbitrary fill | Public submission accepts IDs/fence; it calls the actual risk session. No Fill input or exchange command path. Runtime integration covers rejection/abstention. |
| Duplicate submit or uncertain acknowledgement | Authoritative intent dedupe, commit before acknowledgement, unreconciled projection and journal replay; concurrent duplicate and missed-fill tests. |
| Control/fence change between risk check and fill | Venue lock then risk guard held through commit; supervisor update serialization test and stale/kill/lease/revocation cases. |
| Future/gapped/reordered book | Event/received time, age, sequence and increments validated transactionally. Gap requires full resync; distinct held marks keep distinct ages. |
| Overspend, short sell or excessive approval use | Exact integer cash/holdings reservations, cumulative quantity/notional/cash ceilings, finite shared depth and upward fee rounding; accounting/replay property tests. |
| Incorrect accounting from rounded averages | Integer cost basis is authoritative; average prices only project it. Seed valuations/P&L are checked and low ambient Decimal precision cannot change replay. |
| Mutable returned nested state | Serialized, validated copies at input/output boundaries; mutation-isolation tests. |
| Journal corruption or resource exhaustion | Header/entry/state hashes, sequence checks, 1,000-command and 10-MB bounds; prospective commit validates before mutation. No dedupe eviction. |
| Diagnostic failure leaks state or loses receipt | Closed metadata/counts only; receipt/dedupe committed before logging. Injected diagnostic failure recovers the missed fill without execution retry. |
| Stale portfolio used to replenish risk capacity | No release/reseed/reset. Batch seals at first eligible matching attempt; risk reservations remain retained. |

## Residual risk and required follow-up

Trusted in-process callers could construct competing account objects or alter Python internals.
Do not expose this library directly to tenants or call it a distributed authorization boundary.
An engine/process restart loses authority. Recreated broker views only recover over the same
live simulator. Failure after risk issuance but before venue commit can strand a retained
reservation; the conservative outcome is no retry and no capacity reset.

Before continuous/deployed operation, implement transactional PostgreSQL idempotency and
receipts, durable audit/outbox, RLS and authenticated API authorization, serialized account
ownership/fencing, safe risk generation transitions, Temporal recovery and independently
reviewed operational runbooks. Keep imported historical bundles separate from those stores.
The simulation uses configured costs and synthetic depth, so it does not establish real
venue fill quality, liquidity semantics, data rights or any live-execution eligibility.
The execution-security boundary and paper-only startup gates remain unchanged.
