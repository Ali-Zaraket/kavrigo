# kavrigo-infra

Infrastructure, delivery and operations.

```text
local/        docker compose development stack (implemented)
images/       pinned-base web/API/worker build candidates (not promoted)
tofu/         Separate AWS reference and DigitalOcean paper-staging foundations
kubernetes/   internal-only paper-staging web/API candidate (unapplied)
argocd/       Argo CD applications (not started)
policies/     admission and network policy (not started)
observability/ OpenTelemetry, dashboards, alerts (not started)
runbooks/     operational procedures (not started)
```

Start with [`local/README.md`](local/README.md).

The current staging choice is DigitalOcean Amsterdam (`ams3`):
[`tofu/digitalocean-paper-staging/`](tofu/digitalocean-paper-staging/README.md), recorded in
[ADR 0047](../docs/adr/0047-digitalocean-paper-staging.md). It has not been applied. The earlier
[`tofu/paper-foundation/`](tofu/paper-foundation/README.md) remains an unapplied AWS reference.
The [Kubernetes candidate](kubernetes/paper-staging/README.md) has no public endpoint or worker.
The current [paper launch review](../docs/release/paper-launch-review.md) records the remaining
gates before a public deployment.

## Decisions that constrain what goes here

- OpenTofu with reusable modules, remote encrypted state, separate state per environment, plan
  review in the pull request, and no developer local apply to production (ADR 0016).
- Argo CD pull-based delivery is still the target. GitHub OIDC/ECR and EKS Auto Mode in the
  master spec and ADRs 0015–0016 are AWS-specific; DigitalOcean credential and workload
  delivery controls need a separate, reviewed implementation (ADR 0047).
- Managed stateful services stay outside the DOKS cluster. The DigitalOcean staging root
  covers PostgreSQL/Valkey; Redpanda Cloud, ClickHouse Cloud and Temporal Cloud are separate.
- Environments: `local`, `dev`, `staging`, `paper-prod`, and `live-prod` — which is created only
  after the readiness gate in `MASTER_BUILD_SPEC.md` §47, and is separated from `paper-prod`
  enough to prevent credential or tool crossover.
- The execution deployment is a distinct network and IAM boundary whose role only it can assume
  (ADR 0017).
