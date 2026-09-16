# Step 14 product inspection threat notes

- Browser sessions are ephemeral memory state. Refresh/logout clears identity and query caches.
  Every API request repeats identity, membership, permission and forced-RLS checks.
- The Next handler is an allowlisted facade, not an arbitrary URL proxy. Mutations require an
  exact configured browser origin; redirects are refused. Payload size and upstream time are
  bounded. The UI cannot access an engine command endpoint through this facade.
- Historical paper balances are server-produced decimal strings. The view labels their ledger
  and receipt timestamps. A stored `is_reconciled` value is never labeled as current health.
- Run inspection verifies output hashes and checks decision tenant scope. It projects domain
  decisions/evidence only, not raw model tool state, raw news, account commands or secret material.
  Provider display entitlements must be enforced before licensed feeds are connected.
- A UI paper badge does not authorize trading. Server mode is polled; failed polling removes
  verified status and disables creates. The backend independently refuses live specifications.
- Retry buttons retain the same body/key after an ambiguous error. There is no optimistic
  account confirmation. Draft editing appends versions; it never updates historical specs.
- Local dev identities are unsigned and only appropriate for isolated local development.
  Hosted identity, hardened CSP and a security review are outstanding release gates.
- Read models share the bootstrap PostgreSQL service. Extract them behind engine-owned service
  contracts before repository/service separation. Do not grant the web process database access.

Verification includes tenant/nonmember/viewer API tests, corrupt receipt refusal, exact money
beyond IEEE-754 precision, cross-origin/write-path refusal, real browser versioning and workspace
switching, sign-out storage checks, mode-outage refusal, mobile/reduced-motion and axe checks.
