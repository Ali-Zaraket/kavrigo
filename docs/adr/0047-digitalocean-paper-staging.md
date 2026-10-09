# ADR 0047: DigitalOcean foundation for paper-only staging

- **Status:** Accepted for an unapplied staging plan
- **Date:** 2026-10-09
- **Deciders:** Product owner, engineering
- **Spec reference:** `MASTER_BUILD_SPEC.md` §§16.5–16.14, 24, 36, 47; ADRs 0015–0017 and 0046

## Context

The owner selected DigitalOcean Amsterdam (`ams3`) for a first staging deployment and may
revisit the cloud choice. The master spec's AWS EKS/Aurora/ECR/KMS/Secrets Manager design
cannot be applied unchanged. The existing AWS OpenTofu root has never been applied.

## Options considered

1. Continue with AWS. This preserves the specified service choices but conflicts with the
   owner's current hosting preference.
2. Use DigitalOcean App Platform. This is simpler for a web/API prototype, but does not give
   the intended Kubernetes workload and network boundary for the worker and stateful services.
3. Use DigitalOcean Kubernetes (DOKS) with managed PostgreSQL and Valkey, while keeping
   Redpanda Cloud, ClickHouse Cloud and Temporal Cloud as separately contracted services.
   This keeps the application contracts and managed-stateful-service separation intact.

## Evidence

Checked 2026-10-09: [DOKS isolated worker nodes](https://docs.digitalocean.com/products/kubernetes/how-to/create-clusters-with-isolated-worker-nodes/)
require Kubernetes 1.36+ and a default VPC NAT gateway; isolation can only be chosen at
cluster creation, and the API remains public unless a control-plane firewall is configured.
The [provider's NAT resource](https://docs.digitalocean.com/reference/terraform/reference/resources/vpc_nat_gateway/)
is still labeled Private Preview, so account eligibility must be checked before apply.
[Managed PostgreSQL](https://docs.digitalocean.com/products/databases/postgresql/how-to/create/)
supports version 18; the [database firewall](https://docs.digitalocean.com/reference/terraform/reference/resources/database_firewall/)
supports a Kubernetes cluster as a trusted source. The
[DOKS resource](https://docs.digitalocean.com/reference/terraform/reference/resources/kubernetes_cluster/)
and [container registry resource](https://docs.digitalocean.com/reference/terraform/reference/resources/container_registry/)
are supported by provider 2.104.0. Registry integration grants cluster-wide pull access to
the team's registry set, so it requires a dedicated or reviewed DigitalOcean team.

## Decision

Choose option 3 for **staging only**. Add a separate OpenTofu root for a paper-only DOKS
cluster, VPC with NAT and isolated workers, control-plane firewall, managed PostgreSQL 18,
managed Valkey 8, and a private container registry. Use `ams3` by default, but keep the
region an input. Keep Redpanda, ClickHouse and Temporal as distinct managed-service
dependencies; do not silently replace Redpanda with DigitalOcean Kafka. The AWS root stays
unapplied and unchanged. Do not create `paper-prod` or `live-prod` from this root.

The root is a foundation plan, not an application release. No resource is to be applied
until account access, NAT availability, service-region options, recurring cost, state backend,
legal/data residency and operator CIDRs are reviewed. The registry is for immutable image
digests; build/sign/SBOM and deployment promotion need separate work.

## Security and compliance impact

`LIVE_TRADING_ENABLED=false` and paper mode remain mandatory. DOKS isolates worker public
addresses, but its API endpoint is still public and must allow only named operator CIDRs.
The managed databases are in the VPC and trust only the DOKS cluster. PostgreSQL clients
must verify TLS and use separate migration and application roles with RLS. OpenTofu state
contains provider-generated database credentials even if outputs do not expose them; it
requires an encrypted, access-controlled, versioned, locked backend. DigitalOcean's provider
does not establish AWS KMS/Secrets Manager equivalence. Secret delivery and encryption,
backup/restore, execution-service isolation, external-service connectivity, data rights,
Cloudflare, and independent review remain explicit gates. No exchange credentials belong
in this deployment.

## Operational impact

Staging will depend on DigitalOcean plus Redpanda Cloud, ClickHouse Cloud and Temporal Cloud.
Network routing, egress cost, latency and outage behavior must be measured. NAT is billed
separately and its provider resource may require preview access. If preview access is not
available, stop and revise the plan; do not silently switch to public worker IPs. The
DigitalOcean account/team must be dedicated or registry pull scope explicitly accepted.

## Migration and rollback

Use a new state key for this root; never import AWS resources or reuse its state. To change
cloud provider later, deploy a parallel paper environment, restore and verify PostgreSQL,
replay licensed data where permitted, test tenant isolation and paper reconciliation, then
switch traffic only after go/no-go review. Rollback traffic to the prior healthy environment;
do not destroy authoritative state as a rollback step.
