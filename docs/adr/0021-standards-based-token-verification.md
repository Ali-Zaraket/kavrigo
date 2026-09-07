# ADR 0021: Standards-based token verification behind an identity abstraction

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture, Security
- **Spec reference:** `MASTER_BUILD_SPEC.md` §21; elaborates rather than supersedes the Clerk decision

## Context

`MASTER_BUILD_SPEC.md` §21 selects Clerk for product authentication: passkeys, MFA,
organizations and session management. That decision stands. What it does not settle is *how the
backend verifies a session*, and that choice has security consequences.

Two things pushed against writing a Clerk-specific verifier now:

1. **No credentials exist yet.** `AGENTS.md` is explicit: do not invent provider fields or
   endpoints; use official documentation or mocks until credentials exist. A verifier written
   from recollection of a vendor's API is exactly the kind of code that appears to work and
   fails in a way nobody tests.
2. **`MASTER_BUILD_SPEC.md` §21 itself anticipates re-evaluating Auth0 or WorkOS** when
   SAML/SCIM and enterprise contracts justify it. A verifier welded to one vendor makes that a
   rewrite rather than a configuration change.

## Options considered

1. **Clerk backend SDK.** Least code, and the vendor maintains it. Binds session verification —
   a security-critical path — to one vendor, and could not be written or tested here without a
   Clerk instance.
2. **A JWKS/JWT verifier built on RFC 7515/7517/7519, configured with the issuer, JWKS URL,
   audience and claim names.** Clerk issues standard JWTs, so it is configuration rather than
   code. Fully testable today against a locally generated key pair.
3. **Session introspection against the provider's API on every request.** Strongest revocation
   semantics, adds a network round trip and a hard dependency to every authenticated request.

## Evidence

- `jwt.decode` with an explicit `algorithms` allowlist and `PyJWKClient` key resolution are
  standard, documented PyJWT behaviour (PyJWT 2.13, verified against the installed signature).
- The failure modes guarded against are well-established: `alg=none`, RS256→HS256 confusion
  (why the allowlist contains no symmetric algorithm), missing audience or issuer checks, and
  unbounded JWKS fetching.
- Clerk's specific issuer, JWKS URL and claim names are **not** asserted here. They are
  configuration values that must be confirmed against current Clerk documentation before the
  first real token is verified.

## Decision

Option 2. `IdentityProvider` is a protocol; `JwksIdentityProvider` implements standards-based
verification; `DevIdentityProvider` accepts unsigned `dev:<subject>` tokens for local
development only.

The identity provider's assertions are **inputs, not authorization**. The organization claim is
a hint; the `memberships` table is the decision. A local user record keyed on the provider's
subject means changing provider does not rewrite every foreign key.

Revocation is bounded by token lifetime rather than checked per request. That is acceptable for
research and paper mode; before live execution the trade-off must be revisited, because a
revoked session with an unexpired token is a materially different risk once real funds are
reachable.

## Security and compliance impact

- Algorithms are allowlisted to asymmetric families only. Accepting an HMAC algorithm would let
  anyone holding the public JWKS key mint valid tokens.
- Issuer, audience, expiry and `iat` are all verified; `sub` is required.
- An unrecognised MFA claim shape is treated as **not** verified. Guessing permissively would
  silently unlock exactly the operations MFA protects (`Permission` members in
  `MFA_REQUIRED_PERMISSIONS`).
- The development provider accepts unsigned tokens, so `Settings` refuses to start with it
  enabled outside `KAVRIGO_ENV=local`. A development bypass reachable in a deployed environment
  is an authentication bypass, not a convenience.
- Verification failure reasons are logged and never returned; the client is told only that the
  session is invalid.

## Operational impact

JWKS keys are cached with a bounded lifespan and re-fetched on an unknown key id, so provider
key rotation neither causes an outage nor a fetch on every request.

## Migration and rollback

Switching provider, or moving to a vendor SDK, means adding an `IdentityProvider`
implementation and changing `AUTH_PROVIDER`. No domain, repository or router code changes.

## Consequences

Easier: testing the whole authentication path today, without a vendor account; changing provider
later. Harder: Clerk-specific niceties (organization sync, session listing, webhooks) need
deliberate integration rather than arriving with an SDK — and the claim mapping must be verified
against Clerk's documentation before production use.
