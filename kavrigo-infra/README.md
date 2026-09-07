# kavrigo-infra

Infrastructure, delivery and operations.

```text
local/        docker compose development stack (implemented)
tofu/         OpenTofu modules and environments (not started)
kubernetes/   base manifests and per-environment overlays (not started)
argocd/       Argo CD applications (not started)
policies/     admission and network policy (not started)
observability/ OpenTelemetry, dashboards, alerts (not started)
runbooks/     operational procedures (not started)
```

Start with [`local/README.md`](local/README.md).

## Decisions that constrain what goes here

- OpenTofu with reusable modules, remote encrypted state, separate state per environment, plan
  review in the pull request, and no developer local apply to production (ADR 0016).
- Argo CD pull-based delivery; GitHub OIDC to AWS so CI holds no long-lived cloud credentials.
- EKS Auto Mode for application compute; managed stateful services stay outside the cluster
  (ADR 0015).
- Environments: `local`, `dev`, `staging`, `paper-prod`, and `live-prod` — which is created only
  after the readiness gate in `MASTER_BUILD_SPEC.md` §47, and is separated from `paper-prod`
  enough to prevent credential or tool crossover.
- The execution deployment is a distinct network and IAM boundary whose role only it can assume
  (ADR 0017).
