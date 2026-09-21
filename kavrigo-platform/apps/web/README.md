# Kavrigo web — local paper workspace

Next.js 16.3.4 App Router, React 19.2.8, strict TypeScript, Tailwind 4.3.3,
shadcn Base UI primitives, TanStack Query/Table and generated OpenAPI types.
Requires Node 24 and pnpm 11.19.0. Versions are locked in pnpm-lock.yaml.

## Run

Start the repository Docker stack and apply migrations first. The destination Windows host
uses KAVRIGO_API_HOST_PORT=58300 and KAVRIGO_TEMPORAL_UI_HOST_PORT=58250.

```sh
pnpm install --frozen-lockfile
pnpm dev --hostname 127.0.0.1
```

Open http://localhost:3000. KAVRIGO_API_ORIGIN defaults to http://127.0.0.1:58300.
KAVRIGO_WEB_ORIGIN defaults to http://localhost:3000 and must exactly match the browser origin
for mutations. Set it explicitly when using another hostname or port. Never derive this
allowlist from an untrusted forwarded-host header. See .env.example.

Local mode accepts a named development identity; use the same name to recover membership.
Tokens remain in memory. Refresh signs out. Hosted Clerk sign-in is not implemented.
The API refuses development identity outside its local environment.

## Available behavior

- Create a workspace, select a verified membership, create paper AgentSpec drafts, inspect
  immutable versions and append a new draft version with an idempotency key. The creation form
  generates clearly labeled local rehearsal policy placeholders; these are not approvals.
- Inspect stored runs/stage receipts and structured decisions with supporting/contradicting
  evidence, exact server monetary values, timestamps, version/hash references and reason codes.
- Inspect paper account receipts and workspace audit summaries with backend permissions/RLS.
- Launch an explicitly labeled, execution-disabled Binance Spot Testnet rehearsal for a saved
  BTC/ETH USD.SIM version and inspect its frozen derived evidence in Pulse. The testnet activity
  is simulated; same-key retries reuse the durable input and no order can be submitted.
- Responsive dark/light workspace shell, keyboard navigation/search, reduced motion and
  visible server-confirmed paper status. Mode lookup failure disables creation.

The control plane can store immutable, MFA-gated policy candidates, but the local web sign-in
does not establish MFA and the web proxy does not expose candidate mutations. Review and
approval remain separate for any order-capable paper run. Draft saving validates policy ID
syntax, not existence or approval. Rehearsals use isolated synthetic inputs, an abstaining mock model and a global
risk stop; they do not activate a paper strategy or permit orders. No policy mutation, live
trading, or exchange secret is exposed. Backtest strategy/data wiring, charts, SSE/WS transports,
current provider freshness,
conversational compilation, and hosted identity are explicit carry-overs. Empty screens do not
invent results; historical receipts do not claim current reconciliation or freshness.

## Check

```sh
pnpm lint
pnpm format:check
pnpm typecheck
pnpm test
pnpm build
pnpm test:e2e
```

Browser tests use an isolated API at http://127.0.0.1:58301, configured against a disposable
migrated PostgreSQL database. Override KAVRIGO_TEST_API_ORIGIN only with another test service.
Do not run destructive Python database fixtures concurrently with browser tests on that database.
Playwright defaults to its installed Chromium. On this machine PLAYWRIGHT_CHANNEL=msedge uses
existing Edge; no browser installation is required. Tests launch a production web server on 3000.
Screenshots/traces in test-results are ignored. No hosted CI pass is implied by local checks.

At repository root, export the API with `uv run python scripts/export_openapi.py`, then here run
`pnpm generate:api` and `pnpm exec prettier --write src/lib/schema.ts`. CI checks both boundaries.

## Dependencies and licensing

Geist Sans/Mono come from geist 1.7.2 via next/font/local, with no runtime font CDN. The SIL OFL
notice is retained at public/licenses/geist-OFL.txt. Button/dialog wrappers adapt the official
shadcn base-nova registry (MIT, inspected 2026-09-10) to Kavrigo tokens and 44px targets.
TanStack Table stays outside React Compiler memoization. Lightweight Charts is deferred until
there is an actual time-series API to render; no invented financial series is bundled.

The installed ui-ux-pro-max skill was pinned to upstream revision
7f69fed6a2717900085f1bc3b263721f8ba025e2 with user authorization. Its dense-dashboard guidance
is used; its marketing conversion pattern was discarded. Kavrigo's brand invariants prevail.

## Security and observability

ADRs 0028 and 0030 document the boundary. Proxy routes are allowlisted, fixed-upstream, no-store,
10-second bounded, and limit mutation bodies to 64 KiB. Mutations require the configured
same origin; no cookies or inbound headers other than bearer/idempotency are forwarded.
The rehearsal POST alone accepts an empty body and rejects nonempty bodies.
React renders evidence as text, never HTML or executable links. Backend membership/permissions
and forced RLS remain authoritative. Monetary formatting preserves decimal strings exactly.
Proxy telemetry includes response status and duration only; it excludes tokens, URLs,
workspace IDs, bodies and evidence. The backend retains its correlated request logs.
Hosted CSP/identity/retention and independent security review remain deployment gates.
