# Internal paper-staging workload candidate

This is the next **unapplied** slice of [ADR 0047](../../../docs/adr/0047-digitalocean-paper-staging.md).
It declares the web and API as two-replica, non-root, restricted pods with ClusterIP services,
startup/liveness/readiness probes, disruption budgets, and ingress isolation. The homepage and
`/app` share the web service. No public Ingress, LoadBalancer, worker, market ingester, or
execution gateway is included. The worker and financial runtime still refuse nonlocal mode.

The image names use `registry.invalid` and a zero digest on purpose. This base cannot start as
written. An independently reviewed release overlay must replace both with scanned, signed,
immutable digests from the private registry. `kubectl kustomize kavrigo-infra/kubernetes/paper-staging`
renders the candidate without contacting a cluster; it does **not** authorize apply.
CI parses the rendered resources with `manifest_policy.py` and rejects added resources, public
service exposure, host networking/ports, inline credentials, weakened pod isolation, non-paper
settings, or changes to the two ingress policies. This is a review tripwire for the current
internal-only candidate; it does not prove a cluster enforces NetworkPolicy.

After image signing and digest verification, `release_overlay.py` can write a preview overlay
to a **new** ignored `.local/` directory. It accepts a DigitalOcean registry name plus distinct
`sha256:` manifest digests for web and API, rejects mutable tags and the zero placeholder,
and refuses to overwrite an existing directory. Run `kubectl kustomize` on that new directory
and review the full output. The helper does not inspect signatures, fetch images, create
Secrets, contact Kubernetes, or publish GitOps state.
Run `manifest_policy.py --release <rendered-overlay.yaml>` on the rendered overlay as well;
release mode accepts only nonzero DigitalOcean registry digests and the same paper-only
workload boundary. A passing static check is not signature verification or permission to deploy.

## Required external configuration

Deliver two Kubernetes Secrets through a reviewed secret manager after the cluster exists.
Do not commit their manifests, put values in shell history, or use a manually pasted long-lived
Secret as the final delivery mechanism.

| Secret | Required key | Meaning |
|---|---|---|
| `kavrigo-web-runtime` | `web-origin` | Owned HTTPS origin, equal to the origin used when building the web image. |
| `kavrigo-web-runtime` | `clerk-publishable-key` | Production `pk_live_` key used at image build. |
| `kavrigo-web-runtime` | `clerk-secret-key` | Matching production `sk_live_` key. |
| `kavrigo-api-runtime` | `postgres-dsn` | RLS application role DSN for managed PostgreSQL over verified TLS. |
| `kavrigo-api-runtime` | `auth-issuer` | Production Clerk Frontend API HTTPS origin. |
| `kavrigo-api-runtime` | `auth-jwks-url` | The issuer's `.well-known/jwks.json` endpoint. |
| `kavrigo-api-runtime` | `auth-allowed-parties-json` | JSON array containing the owned web HTTPS origin. |

The manifests hard-code `KAVRIGO_ENV=staging`, `LIVE_TRADING_ENABLED=false`, and
`DEFAULT_TRADING_MODE=paper`. API settings reject local unsigned authentication and invalid
hosted Clerk issuers; the web refuses development keys. The API `/readyz` probe stays failed
until a correctly migrated PostgreSQL database is reachable. The web `/healthz` probe means
only that its process responds; it does not claim the API, Clerk, or market provider is ready.

## Review before any workload apply

1. Finish the DigitalOcean foundation prerequisites in the OpenTofu
   [README](../../tofu/digitalocean-paper-staging/README.md), including account/NAT eligibility,
   state protection, operator access, and cost review. Do not apply the invalid-image base.
2. Build web with the **same** owned origin and production Clerk instance planned for runtime.
   Produce SBOMs, scan final images, sign their digests, and use a separate release overlay to
   replace both `registry.invalid` references. Verify runtime values match the built web image.
3. Provision the secrets above through a reviewed delivery mechanism. Migrate PostgreSQL with
   a separate owner role and test RLS with the application role. Check the cluster's actual
   network-policy enforcement: a policy object alone is not proof of enforcement.
4. The current network policy denies pod ingress except web-to-API, so a future edge/ingress
   controller must receive a narrowly scoped allow policy before any public route. Egress is
   currently unrestricted because managed-service destinations and DNS policy are not yet
   known. Review and constrain it before exposing this environment.
5. Add licensed provider connections, hosted Temporal/worker support, telemetry, alerts,
   backup/restore, and reconciliation tests before a real paper run. Add Cloudflare/TLS and
   hostname routing only after domain ownership and legal/security review.

This candidate is useful for reviewing workload configuration and internal staging mechanics;
it is not a deploy command or a production approval. The
[paper launch review](../../../docs/release/paper-launch-review.md) remains **NO-GO**.
