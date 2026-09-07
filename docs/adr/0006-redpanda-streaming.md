# ADR 0006: Redpanda as the event bus

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §16.5, §18

## Context

The platform is event-driven across market data, features, decisions, risk evaluations, orders and audit. It needs partitioned ordering, replay, schema governance and a managed operational story, without a full Kafka/ZooKeeper operations burden.

## Options considered

1. **Managed Kafka (MSK or Confluent)** — mature, heavier operationally or costlier.
2. **Redpanda (Serverless for dev, Dedicated/BYOC for production)** — Kafka protocol compatible, simpler operational model, BYOC keeps data in our own cloud account.
3. **Ad-hoc queues (SQS/Redis streams)** — insufficient ordering, replay and schema-registry story.

## Decision

Option 2, with Serverless acceptable in development and Dedicated or BYOC multi-AZ in production. BYOC is preferred where security or data-residency requirements justify it. Event contracts are Protobuf with a schema registry; ordering is guaranteed only within a partition key (§18.3).

## Security and compliance impact

BYOC keeps regulated and licensed market data inside our cloud boundary, which matters for data-residency (§64) and provider terms. Tenant-private topics must carry tenant scope in the envelope and be access-controlled.

## Consequences

Easier: Kafka ecosystem compatibility and replay-based testing. Harder: a Kafka-compatible bus is still a stateful system to size and monitor.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
