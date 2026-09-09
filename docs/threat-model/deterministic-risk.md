# Deterministic risk trust boundary

Status: local implementation reviewed by its author; independent security/CODEOWNERS and human
review remain required before deployment. See [ADR 0025](../adr/0025-local-deterministic-risk.md).

| Threat | Implemented local control | Residual requirement |
|---|---|---|
| Model requests more than allocation, changes side/identity, or injects policy | Closed contracts; authoritative version/decision/allocation checks; no model tools in risk | Authenticate coordinator and stored runtime output across services |
| Reused key or concurrent requests spend the same cash | Lock, immutable request fingerprint, decision/intent dedupe and shared reservations | Durable transactional reservation ledger and account ownership |
| Extra fee reservation breaks an earlier concentration cap | Recheck every asset/network after prospective fees; exact integer comparisons | Broker must enforce the permit's cash and quantity ceilings |
| Snapshot remains labelled fresh while waiting | Add elapsed age; recheck at handoff | Authenticated data/supervisor updates and clock monitoring |
| Kill, revocation or expired/stale lease after approval | Monotone controls, lease/token check and terminal refusal | Durable lease acquisition and broker-side fencing |
| Caller mutates frozen-model lists or bypasses Pydantic construction | Detached serialization with errors, full revalidation, detached returned records | In-process trusted Python can still invoke private methods; never expose it as a sandbox |
| Crash after handing off but before acknowledgement | Consume once and retain reservations, including on telemetry failure | Reconcile order/fill state; no automatic release on expiry or restart |
| In-memory state lost/recreated; multiple account sessions | Non-local startup refusal; explicit one-generation scope | Durable ledger, recovery and at-least-once broker idempotency before continuous operation |
| Missing state, unsupported precision, stale data or unknown calendar | Fail closed with reason codes | Trusted account projections, data provenance and reconciliation |
| Audit or telemetry leaks source/model text | Metadata-only telemetry, bounded typed hash-linked local audit | Durable access-controlled audit/outbox and exporter retention review |
| Capacity pressure evicts dedupe or reservation state | Refuse new work and retain existing records | Operational capacity monitoring and durable storage |

No private venue credential, secret-manager role, vendor write API, socket or raw exchange
command is added. Startup live/auth gates and the execution-security repository boundary are
unchanged. Cost/liquidity/group assumptions are synthetic/operator configuration; rights and
provider semantics require verification before external data is connected.
