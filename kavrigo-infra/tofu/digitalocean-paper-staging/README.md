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
   registry, load-balancer and egress charges. Confirm this account can create the
   [NAT resource still labeled Private Preview](https://docs.digitalocean.com/reference/terraform/reference/resources/vpc_nat_gateway/).
2. Record the operator's stable public egress CIDR. The control-plane firewall deliberately
   rejects `0.0.0.0/0`; rotating this address needs a reviewed plan before the old address
   disappears. Use a scoped DigitalOcean token through `DIGITALOCEAN_TOKEN`, never in a
   committed file or shell transcript. Review the registry integration's
   [team-wide image-pull scope](https://docs.digitalocean.com/products/kubernetes/how-to/integrate-with-docr/).
3. Provision a **separate**, encrypted, versioned, access-controlled state backend with
   verified atomic locking and recovery. Put its configuration in ignored `backend.hcl` and
   store backend credentials outside the repository. Do not assume DigitalOcean Spaces meets
   these requirements: its [S3 compatibility](https://docs.digitalocean.com/products/spaces/reference/s3-compatibility/)
   is partial and documents SSE-C, not bucket-level encryption; `use_lockfile` also needs
   conditional writes, which must be proven before use. State can include managed database
   credentials. Never use local state for an applied cluster.
4. Obtain the current DOKS version from the account's Kubernetes options (1.36+ for isolated
   workers), a globally unique registry name and current DB/node sizes. Copy
   `staging.tfvars.example` to ignored `staging.tfvars`, replacing every example value.
5. Generate and review `.terraform.lock.hcl` on the deployment operator platform, commit it,
   and switch CI to `-lockfile=readonly` before the first apply. CI currently validates the
   exact provider version without a committed checksum lock because no deployment account
   or reviewed state backend exists yet.

## Validate and review

```text
tofu fmt -check
tofu init -backend=false -input=false
tofu validate -no-color
tofu init -backend-config=backend.hcl -input=false
tofu plan -var-file=staging.tfvars -out=staging.tfplan
tofu show staging.tfplan
```

Review the plan and state access controls with a second operator before any paid apply.
Never commit `.tfvars`, backend settings, plan or state. After an approved apply, verify the
nodes have no external IPv4, the NAT is default, the Kubernetes API allows only approved
CIDRs, both DB firewalls trust only this cluster, TLS is enforced, and no public DB host is
used by workloads. Record the actual resources and recurring cost.

## Application dependencies after foundation

The [candidate image Dockerfiles](../../images/README.md) are pinned to base digests but
still need final-image SBOM, scan, signature and promotion by digest. Deployment also needs
a private secret-delivery mechanism and Kubernetes manifests for web/API/worker.
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
