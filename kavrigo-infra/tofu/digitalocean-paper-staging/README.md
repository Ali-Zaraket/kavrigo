# DigitalOcean paper staging foundation

This **unapplied** OpenTofu root implements [ADR 0047](../../../docs/adr/0047-digitalocean-paper-staging.md)
and the [state-backend decision, ADR 0048](../../../docs/adr/0048-staging-state-backend.md).
It targets Amsterdam `ams3` by default and creates a VPC, default NAT gateway, isolated-worker
DOKS cluster, control-plane firewall, managed PostgreSQL 18, managed Valkey 8, database
firewalls and a private container registry. It does not enable live trading, deploy workloads,
create a public endpoint, or make Kavrigo ready for a public release.

## Operator prerequisites

1. Create a DigitalOcean account and a dedicated or reviewed team with billing and MFA.
   Check [current regional offerings](https://docs.digitalocean.com/products/kubernetes/)
   and database/registry options in `ams3`; obtain approval for recurring DOKS, NAT, database,
   registry, load-balancer and egress charges. DigitalOcean Support confirmed on 2026-10-13
   that VPC NAT Gateway and DOKS isolated workers are generally available in `ams3` via API or
   Terraform. The [Terraform NAT page](https://docs.digitalocean.com/reference/terraform/reference/resources/vpc_nat_gateway/)
   still says Private Preview; verify actual account/API access with the reviewed plan before
   apply. The root creates the VPC first, so no manual VPC is required.
2. Record the operator's stable public egress CIDR. The control-plane firewall deliberately
   rejects `0.0.0.0/0`; rotating this address needs a reviewed plan before the old address
   disappears. Use a scoped DigitalOcean token through `DIGITALOCEAN_TOKEN`, never in a
   committed file or shell transcript. Review the registry integration's
   [team-wide image-pull scope](https://docs.digitalocean.com/products/kubernetes/how-to/integrate-with-docr/).
3. Provision a **separate private GitLab project** for encrypted, versioned, access-controlled
   OpenTofu state with verified locking and recovery. The AMS3 Spaces preflight passed an
   encrypted read/write but **failed the two-process lock test** on 2026-10-13; do not use
   Spaces or the old `backend.hcl` for this root. GitLab's [managed OpenTofu state](https://docs.gitlab.com/user/infrastructure/iac/terraform_state/)
   documents HTTP lock/unlock endpoints on its Free tier; it still needs our own disposable
   read/write, contention and version-restore tests before any infrastructure apply. Configure
   its URL, lock/unlock methods and credentials through `TF_HTTP_*` process environment
   variables. Supply `TF_ENCRYPTION` at runtime using a dedicated, backed-up key; this root
   enforces client-side state **and plan** encryption. Keep tokens and the encryption
   passphrase out of `.tf`, shell history, plan artifacts and CI logs. State can contain
   generated database credentials. Never use local state for an applied cluster.
4. Obtain the current DOKS version from the account's Kubernetes options (1.36+ for isolated
   workers), a globally unique registry name and current DB/node sizes. Copy
   `staging.tfvars.example` to ignored `staging.tfvars`, replacing every example value.
5. Review the committed `.terraform.lock.hcl` for DigitalOcean provider `2.104.0` and keep CI
   on `-lockfile=readonly`. Provider changes require a deliberate lockfile update and review.

## Validate and review

The operator must provide the [OpenTofu encryption
configuration](https://opentofu.org/docs/v1.12/language/state/encryption/) through `TF_ENCRYPTION`
and the GitLab [HTTP-backend settings](https://opentofu.org/docs/v1.12/language/settings/backends/http/)
through `TF_HTTP_*`. Use the existing backed-up PBKDF2/AES-GCM passphrase, with both `state`
and `plan` methods. The repository contains only `enforced = true`, no secret or default key.
Initialize an **empty disposable GitLab state name first**. Verify encrypted state read/write,
two-process lock contention and state-version recovery before initializing the real staging
state name. The prior `scripts/Test-SpacesState.ps1` is retired after its lock failure; do not
rerun it or use the Spaces preflight object as a staging state source.

The local `scripts/Test-GitLabState.ps1` checks only encrypted read/write using the dedicated
GitLab project and the disposable `preflight-kavrigo-v1` state. It prompts for a short-lived
API-scoped GitLab token and the backed-up encryption passphrase, supplies both through its
temporary process environment while OpenTofu runs, then restores prior values. Do not paste
either secret into chat or a shell command. Run it from a fresh PowerShell process if the
system execution policy blocks unsigned local scripts; do not change the machine-wide policy.
Use `-TestLock` with the **same** passphrase to run a second OpenTofu process against that
disposable state and verify that it is rejected while the first holds the lock, then succeeds
after release. A successful read/write or lock test is not permission to apply the staging
root: state-version recovery must still pass separately.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-GitLabState.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-GitLabState.ps1 -TestLock
```

```text
tofu fmt -check
tofu init -backend=false -lockfile=readonly -input=false
tofu validate -no-color
tofu init -input=false
tofu plan -var-file=staging.tfvars -out=staging.tfplan
tofu show staging.tfplan
```

Review the plan and state access controls with a second operator before any paid apply.
Never commit `.tfvars`, backend settings, plan or state. Confirm that the plan orders VPC, default
NAT gateway, then isolated-worker DOKS creation; isolation cannot be enabled after cluster
creation. After an approved apply, verify the nodes have no external IPv4, the NAT is default,
the Kubernetes API allows only approved
CIDRs, both DB firewalls trust only this cluster, TLS is enforced, and no public DB host is
used by workloads. Record the actual resources and recurring cost.

## Application dependencies after foundation

The [candidate image Dockerfiles](../../images/README.md) are pinned to base digests but
still need final-image SBOM, scan, signature and promotion by digest. An
[internal-only web/API Kubernetes candidate](../../kubernetes/paper-staging/README.md) now exists;
its images are deliberately invalid, secrets are absent, and no worker or public route is
declared. Deployment still needs reviewed secret delivery and hosted worker support.
The web image needs an **owned HTTPS domain** and a production Clerk instance at build time;
`pk_test_`/`sk_test_` cannot be promoted. Configure API JWKS/issuer and party allowlist from
that same instance; see [Clerk handoff](../../../docs/release/clerk-production-handoff.md).
Migrate PostgreSQL with a separate owner role, then connect the application RLS role over
verified TLS. Install ClickHouse Cloud, Redpanda Cloud and Temporal Cloud connections and
prove egress/TLS, schema, replay and restore. Backtest catalog storage must be a licensed,
durable, read-only mount or artifact service, not a local Docker volume. Add Cloudflare/TLS,
GitOps, network policy, OTel/alerts and runbooks before exposing a public route. Keep
`LIVE_TRADING_ENABLED=false` and `DEFAULT_TRADING_MODE=paper` in every workload.

This root is intentionally staging-only. The
[paper launch review](../../../docs/release/paper-launch-review.md) remains **NO-GO** until
independent evidence and product/legal approval exist.
