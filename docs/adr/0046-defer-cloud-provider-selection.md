# ADR 0046: Defer the hosting provider while preserving service boundaries

- **Status:** Accepted for pre-deployment work
- **Date:** 2026-10-04
- **Deciders:** Product owner, engineering
- **Spec reference:** `MASTER_BUILD_SPEC.md` §§16.11–16.14; ADRs 0007, 0015–0017

## Context

The master spec selects AWS EKS Auto Mode, Aurora, S3, KMS, Secrets Manager and ECR. An
unapplied OpenTofu plan now expresses only an EKS/ECR foundation. The product owner may choose
another cloud before deployment. Provisioning AWS resources now would create avoidable migration
work and cost; claiming that another cloud is a drop-in replacement would conceal database,
identity, encryption, networking and operational differences.

## Options considered

1. **Apply the AWS foundation now.** Follows the current spec, but commits spend and location
   before account, jurisdiction and provider selection.
2. **Choose another cloud now.** Could fit a later preference, but no provider, region, cost
   envelope or legal/data-residency requirement has been selected.
3. **Keep AWS as an unapplied reference and defer hosting selection.** Continue product work on
   protocol-level application contracts; choose and review a provider-specific deployment later.

## Evidence

Checked 2026-10-04: [OpenTofu providers](https://opentofu.org/docs/language/providers/)
are separately configured plugins, so the AWS resources in the current root module do not
automatically transfer to another cloud. [Kubernetes Deployments](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
offer a common workload API, but do not solve managed-service or security-control differences.
[Redpanda Cloud's deployment matrix](https://docs.redpanda.com/cloud-data-platform/get-started/cloud-overview/)
lists multiple clouds with different capabilities. The repository search found AWS SDK/resource
references in infrastructure and documentation, not in the web/API/engine application paths.

## Decision

Choose option 3. The AWS foundation remains a reviewable reference, not a commitment to host
there. Keep application services on their existing HTTP, PostgreSQL, ClickHouse, Kafka-compatible,
Temporal and OpenTelemetry contracts. Keep provider-specific infrastructure, secret delivery,
object storage and workload identity behind deployment configuration or adapters. Do not apply
any cloud plan or describe Kavrigo as cloud-portable in production until an alternate provider's
end-to-end staging tests, restore drill and security review pass. A provider choice will require
a new ADR that supersedes the affected AWS-specific ADRs and maps every required control.

## Security and compliance impact

This deferral does not relax workspace isolation, RLS, private networking, KMS-equivalent key
management, secret isolation, audit, backups or licensing. Any alternate deployment must prove
equivalent controls, especially execution-service separation and immutable evidence retention.
No live execution is enabled.

## Operational impact

Hosted setup waits for a selected provider, region, operating entity and cost review. This
delays public availability but avoids paying for an unused EKS cluster. Clerk development
sign-in can be configured locally without choosing the application cloud. Managed service
latency, egress, availability, restore and on-call procedures must be measured for the chosen
topology.

## Migration and rollback

If AWS is selected, review and extend the existing OpenTofu plan before any apply. If another
cloud is selected, add a separate root module and deployment overlay; do not repurpose AWS
state or silently rewrite its plan. Revert this deferral only after the provider decision and
its cost/security evidence are recorded.

## Consequences

The team can continue application and Clerk integration while the host choice remains open.
Production infrastructure, private object storage and hosted run evidence remain blocked.
