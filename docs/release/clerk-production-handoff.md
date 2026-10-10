# Clerk production handoff (paper environment)

Kavrigo's local Clerk development instance proves the sign-in integration, not production
identity. Keep `LIVE_TRADING_ENABLED=false` and `DEFAULT_TRADING_MODE=paper`. A public launch
remains NO-GO until the [paper launch review](paper-launch-review.md) is satisfied.

**2026-10-10 status:** The owner reports control of `kavrigo.com` and a ready Clerk production
instance. Public DNS resolves `clerk.kavrigo.com` and `accounts.kavrigo.com` to Clerk, and
`https://clerk.kavrigo.com/.well-known/jwks.json` returned one RS256 signing key during a
read-only check. This proves DNS and JWKS reachability, not a deployed web session, MFA flow,
tenant isolation, or token acceptance by the API. Production key values remain outside Git.

## Account owner: finish production instance configuration

1. Use the now-controlled `kavrigo.com` domain and the **production** Clerk instance. Follow
   Clerk's DNS/TLS instructions for any newly introduced hostname. The `*.accounts.dev`
   Frontend API and `pk_test_` / `sk_test_` keys are development-only.
2. In the production instance, configure allowed application origins, sign-in/sign-up paths,
   redirect URLs and any OAuth credentials separately. Check which development settings were
   copied; do not assume OAuth, custom paths or other integrations transferred. For the first
   paper-only release, use email/passkey sign-in and avoid requiring SMS, which blocked the
   Lebanon test user. Configure TOTP plus backup codes and a supported step-up path for
   high-impact risk-policy actions. Verify the actual production plan supports the required
   MFA options.
3. Store the `pk_live_` publishable key in the web build environment and `sk_live_` secret key
   in the web runtime secret store. Never commit either key or send it in chat. Configure the
   API Frontend API issuer and exact JWKS URL from the **same production instance**. Record the
   domain, key ownership, rotation contact and incident process in the deployment change.

## Deployment values

| Component | Setting | Required value |
|---|---|---|
| Web build and runtime | `KAVRIGO_ENV` | `staging` or `paper-prod` |
| Web build and runtime | `KAVRIGO_WEB_AUTH_PROVIDER` | `clerk` |
| Web build | `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | `pk_live_...` from the chosen production instance |
| Web runtime secret | `CLERK_SECRET_KEY` | Matching `sk_live_...` |
| Web build and runtime | `KAVRIGO_WEB_ORIGIN` | Exact owned HTTPS origin, such as `https://app.<owned-domain>` |
| API | `AUTH_PROVIDER` / `AUTH_SESSION_PROFILE` | `jwks` / `clerk_v2` |
| API | `AUTH_ISSUER` | Production Clerk Frontend API HTTPS **origin**, no path |
| API | `AUTH_JWKS_URL` | `${AUTH_ISSUER}/.well-known/jwks.json` |
| API | `AUTH_ALLOWED_PARTIES` | JSON array containing the exact `KAVRIGO_WEB_ORIGIN` |

Build the web image **for the target Clerk instance**. Next.js embeds `NEXT_PUBLIC_` values
at build time; changing the publishable key only at runtime cannot repoint an existing image.
Keep the server secret in the runtime secret store, not in the image, repository or CI logs.
An instance switch requires a new web build and matching API issuer configuration.

The web build rejects a missing production environment and development Clerk keys in `staging`
or `paper-prod`. A hosted `dev` environment may use test keys. The API rejects a development
Clerk issuer in staging/paper-prod, a mismatched JWKS URL, unsigned development
identity, and loopback authorized parties outside local. These are configuration checks, not a
substitute for a real-token integration test.

## Staging verification before public access

1. Build and boot the web/API with staging values; verify no keys appear in image layers,
   server logs, client bundle or error messages. Confirm DNS/TLS and CSP allow Clerk's actual
   challenge and sign-in assets.
2. Sign up with a permitted email/passkey path, sign in, sign out, and sign back in. Verify a
   Clerk session token reaches the API, JWT signature/issuer/expiry and `azp` allowlist pass,
   and the workspace membership loads. Confirm a wrong issuer, wrong origin, expired token,
   pending session and missing token are refused.
3. Enable a second factor on a test account and exercise a high-impact risk-policy action.
   Verify missing or old second-factor age is refused, recent MFA succeeds for an authorized
   member, and a different workspace/role cannot perform it. Check the product's step-up UX;
   backend rejection alone is not a complete user flow.
4. Test sign-out, session revocation behavior and key rotation with the actual instance. Record
   the observed revocation window and incident response. Keep the app paper-only throughout.
5. Attach evidence (build digest, scrubbed logs, negative-test results and named reviewer) to
   the launch review. Do not label hosted identity complete from local development sign-in.

Official references: [Clerk production deployment](https://clerk.com/docs/guides/development/deployment/production),
[environment variables](https://clerk.com/docs/guides/development/clerk-environment-variables),
[session tokens](https://clerk.com/docs/guides/sessions/session-tokens),
[manual JWT verification](https://clerk.com/docs/guides/sessions/manual-jwt-verification),
[MFA configuration](https://clerk.com/docs/guides/configure/auth-strategies/sign-up-sign-in-options),
and [Next.js environment variables](https://nextjs.org/docs/app/guides/environment-variables).
