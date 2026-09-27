# ADR 0043: Workspace-scoped reference risk receipt inspection

- **Status:** Accepted for local product inspection
- **Date:** 2026-09-27
- **Spec reference:** `MASTER_BUILD_SPEC.md` §§1.2, 14, 31 and 33

## Context and options

ADR 0042 durably records per-signal deterministic risk evidence, but a workspace reader cannot
inspect it through the product. Showing the raw PostgreSQL stage output would expose unrelated
run internals, make an unbounded response and leave the browser to decide whether a receipt is
valid. A separate audit database would duplicate the authoritative result.

## Decision

Add a read-only, cursor-paginated API projection under the existing workspace run path. It
validates the stored stage hash and complete `BacktestResult` before returning at most 25 typed
receipts. The response distinguishes pending, unavailable historical/early-refusal journals and
recorded journals, including an empty no-signal journal. It carries the journal and replay hashes,
risk totals, cost assumptions, reproducibility hashes and limitations. Research shows a compact
chronological inspection with progressive
disclosure of frozen inputs and explicit synthetic/activation-ineligible language. No action in
this view submits or approves an order.

## Security and compliance

`RUN_READ` membership, application-role row-level security and explicit workspace/run predicates
guard the route. Responses are `private, no-store`; a missing or mismatched artifact fails closed
with a generic error. The API does not return the raw run definition. Receipts include workspace
portfolio and market evidence, so licensed provider display rights must be reviewed before this
view is used with commercial datasets. Current reference inputs are self-authored synthetic data.

## Operations, migration and rollback

The route reads and validates one bounded PostgreSQL stage artifact (at most 10 MB) per request,
then returns a page of at most 25 receipts. This is adequate for local inspection; larger-scale
workloads should add a verified indexed projection without changing the authoritative artifact.
No database migration or workflow history change is required. Rollback removes the route and UI
while preserving existing results and their hashes.
