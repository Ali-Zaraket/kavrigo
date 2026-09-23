# Provider entitlement operations

Kavrigo treats provider rights as activation evidence. A provider label or public endpoint does
not grant commercial, display, derived-data, agent, storage, or tenant rights.

## Event model

The append-only `data_entitlement_events` ledger records two independent scopes:

- a **platform grant** identifies the reviewed contract by hash and records the rights and data
  packs Kavrigo may use;
- a **workspace grant** records the subset of those packs available to one workspace.

Grants have UTC effective and optional expiry times. Revocation is a new event with the same
provider and licence reference. Earlier rows are never edited or deleted. Canonical values are
sorted and unique, and the service verifies every event's content hash before using it.

Activation requires valid grants at the market snapshot time and the assessment time. It binds
the exact platform and workspace event IDs and hashes into the immutable assessment. Required
rights are `application_display`, `derived_data`, `agent_decision`, and `historical_storage`.

## Provisioning boundary

There is no workspace mutation API. The normal application role has read-only access and cannot
self-declare rights. The database owner is the interim local operator path; a future compliance
administration service must preserve the same append-only, separately authorized boundary.

Before recording a production grant, the operator must have:

- written provider terms or an executed contract and a stable internal `license_ref`;
- a content hash of the reviewed contract artifact;
- explicit confirmation of every recorded right and data pack;
- effective, expiry, retention, attribution, deletion and tenant restrictions;
- a named reviewer and a concrete reason for the event.

No production grant is included in the repository or local database setup. Synthetic rehearsals
and exchange testnets remain ineligible regardless of ledger content.

## Failure handling

Missing, expired, revoked, malformed, incomplete or hash-corrupt records block activation. A
licence change is recorded as a later grant or revoke event. If contract rights narrow, ingestion,
retention and user display must also be stopped or changed; the activation gate is one control,
not a substitute for those enforcement paths.

See [ADR 0038](../adr/0038-point-in-time-data-entitlement-ledger.md) and the
[data licence matrix](data-license-matrix.md).
