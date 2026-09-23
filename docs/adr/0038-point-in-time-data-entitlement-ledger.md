# ADR 0038: Point-in-time data-entitlement ledger

- **Status:** Accepted for the local control-plane slice
- **Date:** 2026-09-23
- **Deciders:** Principal engineering agent
- **Spec reference:** `MASTER_BUILD_SPEC.md` §§8.3, 16.6, 20 and 46

## Context

Paper activation must prove that Kavrigo may use each evidence provider and that the requesting
workspace may use every selected data pack. A provider name or `license_ref` on an evidence item
is provenance, not proof of rights. Current synthetic and testnet sources are deliberately
ineligible, and no production provider contract is approved.

The proof must be evaluated at both the evidence timestamp and assessment timestamp. It must
survive later contract changes, support revocation without rewriting history, remain isolated by
workspace, and be impossible for a normal workspace caller to self-assert.

## Options considered

1. **Boolean provider configuration** — simple, but loses contract identity, tenant scope,
   point-in-time validity and revocation history.
2. **Mutable provider and workspace entitlement rows** — queryable, but overwrites the evidence
   needed to explain historical activation decisions.
3. **One append-only event ledger with platform and workspace scopes** — preserves legal and
   tenant history, supports point-in-time evaluation, and lets an assessment bind exact records.

## Evidence

The master specification identifies data licensing as a launch blocker, requires tenant and plan
entitlements, and assigns entitlement state to PostgreSQL. PostgreSQL 18 documentation reviewed
2026-09-23 confirms that row security can restrict visible rows, `FORCE ROW LEVEL SECURITY`
applies policy evaluation to table owners, grants can be limited by command, and `NULLS NOT
DISTINCT` can make a nullable scope key unique.

- [Row security policies](https://www.postgresql.org/docs/18/ddl-rowsecurity.html)
- [Constraints and `NULLS NOT DISTINCT`](https://www.postgresql.org/docs/18/ddl-constraints.html)
- [`GRANT`](https://www.postgresql.org/docs/18/sql-grant.html) and
  [`REVOKE`](https://www.postgresql.org/docs/18/sql-revoke.html)

## Decision

Store canonical `data_entitlement_events` in PostgreSQL. Each event is a grant or revocation for
one provider and `license_ref`, with an effective time and optional expiry.

Platform grants are global. They bind a contract content hash, allowed data packs, and the four
rights required by the current agent path: application display, derived-data use, agent decision
use, and historical storage. Workspace grants contain the data packs that tenant may use and
inherit the platform contract and rights.

Activation evaluates the latest effective platform and workspace events at both the frozen
market-snapshot time and assessment time. Every required pack must be covered at both points.
The assessment stores canonical references and hashes for the exact events used. Missing,
expired, revoked, corrupt, incomplete, synthetic, or testnet evidence fails closed.

The application role receives read access only. There is no user-facing mutation endpoint.
Until a separate compliance administration surface exists, only the database-owner/operator
path may append events. No provider grant is seeded by this change.

## Security and compliance impact

Forced row security exposes global platform events and the current workspace's events while
hiding other workspace grants. The application role cannot insert, update, delete, truncate,
reference, or trigger against the ledger. An append-only trigger rejects owner updates and
deletes; corrections are later events.

The ledger stores a contract content hash and internal reference, not contract text, API keys,
provider credentials, or market payloads. Event hashes are checked before activation. This
control records an engineering fact; legal approval still comes from an authorized reviewer.

## Operational impact

Entitlement evaluation adds one indexed read to activation assessment and fails closed when the
ledger is unavailable or inconsistent. Operators must append grants and revocations with UTC
effective times, canonical sorted values, a reason, actor identity, and a matching event hash.
Expiry and revocation require monitoring before supervised paper activation is enabled.

## Migration and rollback

Migration 0007 creates the ledger, policies, privileges, trigger and lookup index, then adds the
event-reference document and hash to activation assessments. Existing assessments receive the
canonical empty reference list during migration.

Rollback removes those assessment columns and drops the ledger. It does not alter agent
versions, provider contracts, market data, policy approvals, accounts, orders, or execution
state. Historical entitlement events should be exported before rollback in a non-development
environment.

## Consequences

Activation can now prove data rights from immutable records rather than a hard-coded provider
allowlist. A licensed evidence run can pass the entitlement gate once authorized records exist.
The overall activation decision remains blocked because supervised activation support is not yet
implemented. Provider procurement, contract review, licensed ingestion, retention enforcement,
attribution and operational monitoring remain separate requirements.
