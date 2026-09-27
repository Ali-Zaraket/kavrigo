# ADR 0044: Honest control-plane readiness and simulation disclosure

- **Status:** Accepted for local validation
- **Date:** 2026-09-27
- **Spec reference:** `MASTER_BUILD_SPEC.md` §§24, 31 and 47

## Context and options

The API previously labelled ClickHouse, Redpanda and Temporal `ok` whenever an address was
configured, without connecting to them. It also returned HTTP 200 when PostgreSQL was absent or
unreachable, even while the JSON body said `degraded`. Kubernetes treats any HTTP 200–399 probe
response as success, so a body-only failure would still receive traffic. The mode disclosure also
implied real market data for current synthetic and testnet runs.

We considered active probes for every configured service. This control plane does not own their
health clients or use them for its tenant-scoped read authority; adding superficial TCP checks
would recreate false confidence. Their service/worker health belongs to separate supervision.

## Decision

`/healthz` remains process liveness. `/readyz` probes PostgreSQL with a two-second bound and
returns HTTP 503 with a typed degraded body when it is absent, unavailable or too slow. Other
configured dependencies are reported `configured_unverified`, never `ok` from configuration
alone. A healthy PostgreSQL control plane with the expected schema returns 200 even when
downstream integrations are unverified; dispatch uses a durable outbox and can remain queued. The
platform-mode disclosure identifies current local synthetic and testnet evidence accurately.

**Schema amendment, 2026-09-27:** Connectivity alone can succeed while migrations are missing.
The same two-second readiness bound now checks the application role can read
`kavrigo.alembic_version` and that its sole revision equals the API image's expected head.
Absent, older or branched revision rows return HTTP 503 with `schema=mismatch`; a missing version
table, connection failure or probe failure returns `unavailable`. A test compares the pinned
revision to Alembic's migration head, and an integration test checks the least-privilege role
against the migrated database.

The local Compose API healthcheck uses `/readyz` so its container status reflects the same
database dependency. `/healthz` remains available to distinguish a live process from readiness.

## Evidence

- [Kubernetes HTTP probe semantics](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/): only HTTP 200–399 is success; failed readiness removes a pod from Service traffic.
- [FastAPI response status handling](https://fastapi.tiangolo.com/advanced/response-change-status-code/): a `Response` parameter can set a dynamic status while retaining response-model validation.
- [Alembic version table and branches](https://alembic.sqlalchemy.org/en/latest/branches.html): multiple migration heads can create multiple `alembic_version` rows, so readiness requires the expected singleton revision.

## Security, operations and rollback

The probe reveals only coarse dependency state, not hosts, credentials or exception text. A
bounded PostgreSQL or schema failure prevents traffic from reaching an API unable to enforce
tenant authority or use its expected tables. Worker, provider and data-health readiness remain
separate release gates; this probe does not assert them. No migration is needed. Rollback restores
the prior response shape but
would reintroduce misleading health and should occur only with a replacement probe.
