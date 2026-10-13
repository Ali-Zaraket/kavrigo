# DigitalOcean paper staging foundation

This **unapplied** OpenTofu root implements [ADR 0047](../../../docs/adr/0047-digitalocean-paper-staging.md).
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
3. Provision a **separate**, private, versioned, access-controlled state backend with
   encryption, verified locking and recovery. DigitalOcean now [documents Spaces as a remote
   state backend with `use_lockfile = true`](https://docs.digitalocean.com/products/spaces/reference/terraform-backend/).
   Use a dedicated `ams3` bucket, configure it through ignored `backend.hcl`, and keep its
   credentials in environment variables or a secret manager. Enable [bucket
   versioning](https://docs.digitalocean.com/products/spaces/how-to/enable-versioning/)
   explicitly. Spaces [documents SSE-C rather than bucket-level
   encryption](https://docs.digitalocean.com/products/spaces/reference/s3-compatibility/),
   so this root enforces OpenTofu state **and plan** encryption. Supply a reviewed
   `TF_ENCRYPTION` configuration at runtime using a dedicated, backed-up key;
   never put its passphrase in `.tf`, `backend.hcl`, shell history, or CI logs.
   Without `TF_ENCRYPTION`, this root must fail before writing state or plans.
   Prove concurrent lock behavior and a version restore using a disposable state key before
   the first infrastructure apply. State can include managed database credentials. Never use
   local state for an applied cluster.
4. Obtain the current DOKS version from the account's Kubernetes options (1.36+ for isolated
   workers), a globally unique registry name and current DB/node sizes. Copy
   `staging.tfvars.example` to ignored `staging.tfvars`, replacing every example value.
5. Generate and review `.terraform.lock.hcl` on the deployment operator platform, commit it,
   and switch CI to `-lockfile=readonly` before the first apply. CI currently validates the
   exact provider version without a committed checksum lock because no deployment account
   or reviewed state backend exists yet.

## Validate and review

The operator must first provide Spaces credentials through ephemeral `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY` environment variables, and the [OpenTofu encryption
configuration](https://opentofu.org/docs/v1.12/language/state/encryption/) through `TF_ENCRYPTION`.
Use a dedicated PBKDF2/AES-GCM key for this state, protect and back up the passphrase in a
password manager, and include both `state` and `plan` methods. The repository only contains
`enforced = true`; it contains no passphrase or default encryption key. The operator-local
`backend.hcl` contains the bucket endpoint, name, state key, `use_lockfile = true`, and the
DigitalOcean S3 compatibility settings, but no credentials. Verify this file and the encryption
setup with a disposable state key and no infrastructure resources before the first real init.
On Windows, run `scripts/Test-SpacesState.ps1` from PowerShell. It prompts for the Spaces key pair
and the backed-up encryption passphrase without echoing them, temporarily sets process-only
environment variables, and writes/reads a built-in `terraform_data` marker at
`preflight/ams3-state-v1.tfstate`. It restores the prior environment afterward. This preflight
does **not** create a VPC, cluster, database, registry, or other DigitalOcean infrastructure.
It verifies state access and an encrypted round trip, not lock contention or version recovery;
run those separate tests before the real staging apply.

```text
tofu fmt -check
tofu init -backend=false -input=false
tofu validate -no-color
tofu init -backend-config=backend.hcl -input=false
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
