# kavrigo-platform

Product and control plane.

```text
apps/web/          Next.js paper workspace and stored receipt inspection
services/api/      FastAPI control plane
```

## Control-plane API

```text
GET    /healthz  /readyz  /v1/platform/mode
GET    /v1/me
GET    /v1/workspaces                                          POST /v1/workspaces
GET    /v1/workspaces/{workspace_id}
GET    /v1/workspaces/{workspace_id}/agents                    POST .../agents
GET    /v1/workspaces/{workspace_id}/agents/{agent_id}         DELETE .../{agent_id}   (archive)
GET    .../agents/{agent_id}/versions                          POST .../versions
GET    .../agents/{agent_id}/versions/{version}
```

`GET /v1/platform/mode` exists so the web client renders paper/live status from the server
rather than a build-time constant — paper and live must be impossible to confuse
(`MASTER_BUILD_SPEC.md` §31), and that guarantee cannot rest on the frontend.

### Two gates that refuse at startup rather than branching at runtime

- `LIVE_TRADING_ENABLED=true` makes the process fail to start (ADR 0001): the capability it
  would advertise does not exist.
- `AUTH_PROVIDER=dev` outside `KAVRIGO_ENV=local` makes the process fail to start (ADR 0021):
  the development provider accepts unsigned tokens, so reaching it in a deployed environment
  would be an authentication bypass.

### Authorization chain

```text
bearer token  → IdentityProvider.verify   is this a valid session?
              → local user upsert          who is this, in our terms?
              → membership lookup          do they belong to this workspace?
              → permission check           may they, and is MFA satisfied?
              → RLS-scoped transaction     can the database even see other rows?
```

The workspace comes from the URL path and is then validated against a stored membership. A
client-supplied identifier never grants access on its own. A non-member gets `404`, not `403` —
confirming a workspace exists to someone with no standing in it lets an attacker enumerate
tenants.

High-impact permissions (`EXCHANGE_CONNECTION_WRITE`, `RISK_POLICY_WRITE`, `AGENT_PROMOTE`,
`WORKSPACE_DELETE`) additionally require a verified second factor, and a denial for that reason
is distinguished from a role denial so the client can prompt to re-authenticate.

### Immutable versioning

There is deliberately **no endpoint that changes an agent's behaviour in place**. Editing means
`POST .../versions`, which appends. `UPDATE` and `DELETE` on `agent_versions` and `audit_events`
are refused by database triggers, so the guarantee does not depend on application discipline.

### Database

Two roles: `kavrigo` owns the schema and runs migrations; `kavrigo_app` is what the application
connects as — not a superuser, not the owner, without `BYPASSRLS`, DML only. Row-level security
is `ENABLE`d and `FORCE`d on every tenant-scoped table. A repository that forgets its
`workspace_id` predicate returns nothing rather than another tenant's rows.

```bash
make up && make migrate      # start Postgres and apply migrations
make test-integration        # RLS, immutability and end-to-end API tests
```

Conventions for every future endpoint are in [`docs/api/conventions.md`](../docs/api/conventions.md).

## Web application

The local paper UI uses Next.js 16.3.4, React 19.2, Tailwind 4.3, adapted shadcn/Base UI
primitives, TanStack Query/Table and a generated OpenAPI client. See
[apps/web/README.md](apps/web/README.md) for startup and verification. It supports immutable
paper drafts, run/evidence inspection, stored portfolio receipts and audit. Hosted sign-in,
run launch and real market charts remain pending.

Read-only inspection routes: `GET .../runs`, `GET .../runs/{run_id}`,
`GET .../paper/accounts`, `GET .../audit`, all under authenticated workspace scope.

## Design system

The user-authorized **ui-ux-pro-max** skill is installed at upstream commit
`7f69fed6a2717900085f1bc3b263721f8ba025e2`. Use its accessibility and craft guidance.
**Kavrigo's brand invariants override the skill's recommendations where they conflict.** The
skill proposes a design system from a product description; Kavrigo already has one, and it is
mandated in `AGENTS.md` § "UI / brand design directive" and `MASTER_BUILD_SPEC.md` §30.8:

- fixed tokens — `ink-950 #090D12`, `ink-900 #111821`, `ink-750 #223041`, `text-50 #EAF1F8`,
  `text-400 #91A2B5`, `brand-400 #5CC8FF`, `evidence-400 #4ED7B1`, `warning-400 #F2B84B`,
  `risk-400 #FF6B75`;
- Geist Sans and Geist Mono, tabular numerals on every financial figure;
- direction: **institutional trading terminal × modern AI lab**;
- green and red are reserved for financial semantics and are never the only status channel;
- explicitly prohibited: casino neon, cyberpunk, heavy gradients and glow, glossy 3D coins, fake
  profit screenshots. The skill's flashier styles — glassmorphism, claymorphism, neumorphism —
  are therefore out of scope for Kavrigo whatever it recommends.

So: feed the skill Kavrigo's constraints as input and use its craft output, rather than letting
it generate a competing design system. Dark-first with an excellent light mode, WCAG 2.2 AA.
