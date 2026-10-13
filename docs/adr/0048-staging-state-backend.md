# ADR 0048: GitLab-managed OpenTofu state for DigitalOcean staging

- **Status:** Accepted for an unapplied staging plan; backend integration unverified
- **Date:** 2026-10-13
- **Deciders:** Product owner, engineering
- **Spec reference:** `MASTER_BUILD_SPEC.md` §16.14; ADR 0047

## Context

ADR 0047 requires encrypted, versioned, access-controlled **and locked** remote state before
applying DigitalOcean resources. A private, versioned AMS3 Spaces bucket passed an encrypted
read/write preflight with OpenTofu 1.12.0. The deliberate two-process contention test did not
pass: while one apply held a 25-second `local-exec` step, the second plan did not report the
expected lock conflict; the first apply then failed to release its `.tflock` because its
`GetObject` returned `NoSuchKey` (404). The test used only a built-in `terraform_data` marker
under `preflight/ams3-state-v1.tfstate`; the actual staging state key was never initialized
or written, and no DigitalOcean infrastructure was created.

DigitalOcean [documents Spaces as a state backend with `use_lockfile = true`](https://docs.digitalocean.com/products/spaces/reference/terraform-backend/),
but this observed contention and release failure is sufficient to reject it for Kavrigo state
until the behavior is explained and a repeatable contention test passes. OpenTofu's S3 lock
uses [conditional object writes](https://opentofu.org/docs/v1.10/language/settings/backends/s3/);
DigitalOcean's [PutObject API header list](https://docs.digitalocean.com/reference/api/spaces/)
does not list `If-None-Match`. That omission may explain the failure, but is not proven as its
root cause. Do not `force-unlock` or run another concurrent test against this bucket without
first verifying the current lock and state objects.

## Options considered

1. Continue with Spaces `use_lockfile`. Rejected after the failed live contention test.
   Encryption and versioning alone do not prevent concurrent state corruption.
2. Store encrypted state in a GitHub repository and serialize GitHub Actions jobs. This could
   serialize one workflow, but does not give local operators and all CI clients an OpenTofu
   backend lock API. It would rely on a convention rather than a verified backend lock.
3. Use the OpenTofu PostgreSQL backend. It [uses advisory locks](https://opentofu.org/docs/v1.13/language/settings/backends/pg/),
   but a managed database would have to be provisioned and secured before the foundation
   root can create it, introducing a separate bootstrap system.
4. Use a dedicated private GitLab.com project solely for GitLab-managed OpenTofu state, while
   keeping GitHub as the code and CI source. GitLab [documents this state service on its Free
   tier](https://docs.gitlab.com/user/infrastructure/iac/terraform_state/) with locking,
   versions and access control through the OpenTofu HTTP backend. It adds one external
   account/service, but provides a supported state API with explicit lock/unlock endpoints.

## Decision

Choose option 4 for the **unapplied paper-staging root**. Use an empty `backend "http" {}` in
the root and configure the state address, lock/unlock addresses and credentials only through
`TF_HTTP_*` process environment variables. Keep OpenTofu client-side state and plan encryption
enforced with a dedicated backed-up key. Use a separate private GitLab project for state,
with only required maintainers. GitHub remains the source repository; this decision does not
move application code or CI to GitLab.

The decision is conditional on a fresh read/write, two-process lock contention, state-version
and restore test against GitLab using a disposable state name. No staging infrastructure apply
may proceed until those checks pass and the actual state project, membership and token scope
are reviewed. The earlier Spaces bucket contains only disposable preflight state; it is not a
source for migration into the production staging state name.

## Security and compliance impact

State may contain generated database credentials. Keep the GitLab project private and its
membership narrow; use an API-scoped token with Maintainer/Owner rights only in a temporary
operator process or an approved secret store, never in `.tf`, backend config, plan artifacts,
shell history or logs. GitLab encrypts managed state at rest, but Kavrigo still requires
OpenTofu client-side encryption so a downloaded state version is not readable without the
separately backed-up passphrase. Losing that passphrase makes state unrecoverable. Do not use
`-lock=false` or a GitHub-file workaround for applies.

## Operational impact

GitLab.com availability becomes a dependency for plans/applies and recovery. The dedicated
project must be protected with MFA and limited access; the state encryption key must be
available to approved operators and CI only when needed. Version restore and lock behavior
must be rehearsed before applying any DigitalOcean resources. The failed Spaces preflight
is retained as evidence but must not be used for the real staging state.

## Migration and rollback

No real staging state or resources exist, so initialize a **new** GitLab state name after
verification; do not migrate the disposable Spaces marker. If GitLab fails its preflight,
stop and select another locking backend through a new ADR. Do not fall back to Spaces or
unencrypted local state for applied infrastructure. If a later backend migration is needed,
take a verified encrypted backup and use OpenTofu's backend migration with an explicit
rollback plan; never delete the prior state before validating the new one.
