# Paper launch review — updated 2026-10-09

**Decision: NO-GO for a public paper launch.** This is an engineering self-review, not an
independent security assessment or legal approval. The local app and synthetic/testnet rehearsals
are useful for development; they do not prove production operation with licensed real prices.
`LIVE_TRADING_ENABLED=false` remains mandatory. Live execution is outside this review.

| Gate | Current evidence | Exit condition |
|---|---|---|
| Licensed BTC/ETH market data | The entitlement ledger and fail-closed activation assessment exist, but no production grant, paid provider key, retention rule or public real-data pipeline is installed. | Record reviewed contract rights and active subscription; verify attribution, rate limits, retention and deletion; replay a licensed point-in-time snapshot through the agent, risk and paper account. |
| Paper activation and policy | Immutable policy review/approval exists. `activation_support` deliberately fails because production paper issuance is absent. | Bind approved policy, immutable agent version, fresh entitled evidence and account generation to an idempotent paper run; verify rejection, stale data, duplicate, crash and reconciliation scenarios. |
| Hosted identity | Standards-based JWT/JWKS checks exist; local dev identity cannot start in nonlocal environments. Web/API deployment guards reject development Clerk configuration in hosted mode. A Clerk development session created a local workspace and loaded owner membership through the API. The [production handoff](clerk-production-handoff.md) is ready; staging and production-instance evidence is pending. | Configure a production Clerk instance and owned domain, session issuer/JWKS, allowed parties and MFA policy; test real member/role changes, logout, revocation window and tenant separation in staging. |
| Hosted infrastructure | Local Compose is healthy. DigitalOcean `ams3` is selected for a paper-only staging foundation (ADR 0047), which is unapplied; the AWS root remains a reference. No managed accounts, state backend or hosted workloads are configured. | Review account/NAT eligibility, region, cost and encrypted/locked state; plan/apply the isolated DOKS and managed DB foundation; configure Redpanda/ClickHouse/Temporal, secret delivery, GitOps and edge controls; pass a staged run and restore exercise. |
| Delivery and observability | All nine CI jobs passed on commit `4569e15`; local OTel and golden boundary evals pass. No signed ECR promotion, hosted dashboards, alerts or SLO measurements exist. | Build immutable signed images with SBOM, deploy by digest, alert on provider/worker/risk/data health, exercise rollback and incident runbooks, and measure SLOs. |
| Security and compliance | CodeQL, Trivy and secret scanning passed at the recorded CI checkpoint; no independent assessment exists. | Independent threat-model/code/IaC review and penetration test; resolve findings; business/legal determine launch entity, jurisdiction, privacy/retention, provider terms and brand/domain clearance. |

## Evidence required at the go/no-go meeting

1. Exact code and image digests, green CI run, environment plan and reviewed change record.
2. Licensed-data agreement/plan, entitlement event hashes, attribution screenshots and a tested
   deletion procedure for cancellation or expiry.
3. Real Clerk token and tenant-isolation test results; MFA and incident-access evidence.
4. Staging paper run using fresh licensed BTC/ETH data: immutable evidence, structured decision,
   deterministic risk receipt, paper order/fill/portfolio receipt, replay and reconciliation.
5. Backup/restore, failover, stale-data, provider outage, worker crash and duplicate-submit drills.
6. Monitoring dashboard, on-call owner, alert routing, rollback command and independent security
   sign-off with residual risks accepted by the named release owner.

Do not mark this review green by checking boxes without linked artifacts. A deployment foundation
plan is not an operating service, and a synthetic backtest is not evidence of market performance.

Relevant baselines: [master spec](../../MASTER_BUILD_SPEC.md), [current progress](../../PROGRESS.md),
[data rights](../product/data-license-matrix.md), [provider entitlement operations](../product/provider-entitlements.md),
and [durable workflow threat model](../threat-model/durable-workflows.md).
