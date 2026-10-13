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
   documents HTTP lock/unlock endpoints on its Free tier. Disposable encrypted read/write and
   two-process lock contention and separate-state version recovery passed on 2026-10-13.
   Configure its URL, lock/unlock methods and
   credentials through `TF_HTTP_*` process environment
   variables. Supply `TF_ENCRYPTION` at runtime using a dedicated, backed-up key; this root
   enforces client-side state **and plan** encryption. Keep tokens and the encryption
   passphrase out of `.tf`, shell history, plan artifacts and CI logs. State can contain
   generated database credentials. Never use local state for an applied cluster.
4. Obtain the current DOKS version from the account's Kubernetes options (1.36+ for isolated
   workers), a globally unique registry name and current DB/node sizes. For manual planning,
   copy `staging.tfvars.example` to ignored `staging.tfvars`, replacing every example value.
   The guided plan helper below instead writes ignored inputs under `.local/`.
5. Review the committed `.terraform.lock.hcl` for DigitalOcean provider `2.104.0` and keep CI
   on `-lockfile=readonly`. Provider changes require a deliberate lockfile update and review.

For the next read-only planning step, create a short-lived **Read Only** DigitalOcean API
token in Account → API. Run `Get-DigitalOceanStagingOptions.ps1` in a fresh PowerShell
process; it prompts for the token without saving it and lists current DOKS `ams3`, worker
size and Kubernetes version options. The lookup uses DigitalOcean's documented
[`GET /v2/kubernetes/options`](https://docs.digitalocean.com/products/kubernetes/reference/api/)
endpoint and does not create resources. Do not paste the token into chat or a command.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Get-DigitalOceanStagingOptions.ps1
```

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
after release. Use `-TestRecovery` to read an older GitLab state version and restore it into
a newly named, disposable state using OpenTofu's normal lock and encryption. It never
overwrites the original preflight state. The new state name has an independent lineage and
serial history; the script checks the recovered marker contents. Its temporary plaintext
state file is under ignored `.local/` and is removed when the script exits; inspect and
remove it after an interrupted run. No staging infrastructure apply is permitted until this
recovery check passes.

After the preflight passes, `Plan-DigitalOceanStaging.ps1` prompts for an unused registry
name, your current public IPv4 address with `/32`, the short-lived DigitalOcean **Read Only**
token, the GitLab state token and the backed-up state passphrase. It rechecks the selected
Kubernetes version, planned PostgreSQL/Valkey options, and registry tier/region against
DigitalOcean's current read-only options endpoints, uses the fresh
`paper-staging-ams3-v1` GitLab state name, and writes a non-secret variable file plus an
encrypted plan only under ignored `.local/`. The default version is `1.36.5-do.0`, which
the account listed on 2026-10-13; pass `-KubernetesVersion` if a newer reviewed version is
chosen. The plan does **not** create DigitalOcean resources. Review the full plan, state
access, service availability and recurring cost before any apply.

Run the read-only review helper after planning. It prompts for the **same**
state-encryption passphrase and checks the saved plan against the expected
eight-resource foundation without printing the token, passphrase or operator
IP address. Do not paste raw `tofu show -json` output into chat: OpenTofu
documents that JSON plan output can contain sensitive values in plain text.
A passing helper is a preliminary check, not authorization to incur charges.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Review-DigitalOceanStagingPlan.ps1
```

To deploy the reviewed plan, first accept the recurring charges and create a
short-lived DigitalOcean **Custom Scopes** token in Account → API for this
staging apply. The Read Only planning token cannot create resources. The token
needs read/create access to VPCs, NAT gateways, Kubernetes clusters, managed
databases and registries; Kubernetes update for registry integration; database
update for firewalls; and database credential viewing for provider state. In
DigitalOcean's picker, select the required dependent read scopes as prompted.
See the [current token scope list](https://docs.digitalocean.com/reference/api/scopes/)
and [Kubernetes registry integration API](https://docs.digitalocean.com/products/kubernetes/reference/api/).
Do not paste either token or the passphrase into chat. Revoke the temporary
DigitalOcean token after the apply and verification are complete.

The helper below rechecks the saved encrypted plan immediately before apply;
it does not silently replan. It requires `-ApproveMonthlyCharges` and a typed confirmation because
[OpenTofu does not prompt when applying a saved plan](https://opentofu.org/docs/v1.13/cli/commands/apply/).
If apply fails after creating some resources, inspect the GitLab state and
DigitalOcean account before retrying. Do not destroy or replan blindly.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Apply-DigitalOceanStaging.ps1 -ApproveMonthlyCharges
```

As a rough October 2026 floor for the current defaults, three 2-vCPU/4-GiB workers
($72/month), the HA control plane ($40), size-1 NAT ($40), a Basic registry ($5), and
single-node PostgreSQL and Valkey (starting at $15 each) total about **$187/month**.
This excludes transfer overages, extra storage, external data/workflow services, a load
balancer and any larger database or node choices. Verify actual account pricing and the
reviewed plan before paying. Sources: [Droplets](https://www.digitalocean.com/pricing/droplets),
[DOKS](https://docs.digitalocean.com/products/kubernetes/details/pricing/),
[NAT](https://docs.digitalocean.com/products/networking/vpc/details/pricing/),
[registry](https://www.digitalocean.com/products/container-registry),
[PostgreSQL](https://docs.digitalocean.com/products/databases/postgresql/details/pricing/),
and [Valkey](https://docs.digitalocean.com/products/databases/valkey/details/pricing/).

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Plan-DigitalOceanStaging.ps1
```

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-GitLabState.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-GitLabState.ps1 -TestLock
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-GitLabState.ps1 -TestRecovery
```

For a manual plan after setting the same credentials and encryption environment, use:

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
