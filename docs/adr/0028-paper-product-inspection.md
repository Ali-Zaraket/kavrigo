# ADR 0028: Paper product inspection and browser boundary

Status: accepted for local bootstrap, 2026-09-10. Implements step 14 and ADR 0013.

The browser needs workspace membership, immutable AgentSpec editing and durable run/account
inspection. Next.js uses the FastAPI control plane through an allowlisted same-origin route
handler. The browser holds its bearer token only in memory; no token is written to local
storage, cookies, URLs or rendered server HTML. Refresh requires sign-in again. Local unsigned
identities remain explicitly development-only; the API's environment gate remains authoritative.
Hosted Clerk sign-in remains a separate integration before deployment.

Read-only FastAPI projections select explicit columns from engine-owned PostgreSQL receipts
under the existing membership, permission and forced-RLS controls. This bootstrap shares the
database deliberately, introduces no second authority, and does not import the engine executor
into the API. Output stage hashes and tenant bindings are checked. Account views describe a
stored receipt at its timestamp, not fresh/reconciled current execution authority. No write
interface to accounts or workflow inputs is introduced by inspection.

Alternatives: direct browser database access violates tenant and service boundaries; copying
full engine payloads exposes unnecessary internal state; inventing sample results in the product
misrepresents capability. Empty/unavailable screens are explicit until the corresponding
pipeline supplies data. Before repository separation, replace shared-table reads with an
engine-owned read service behind the same response contracts. Rollback removes these additive
routes and the web deployment; no migration or trading-state mutation is required.

Dependencies: Next.js 16.3.4, React 19.2 patch, Tailwind 4.3 patch, shadcn Base UI for accessible
primitives, TanStack Query for scoped request lifecycle, TanStack Table for inspectable lists,
OpenAPI TypeScript/fetch for generated contracts, Geist fonts under SIL OFL. Lightweight Charts
is reserved for real time-series endpoints; no empty or fabricated performance chart is needed.

Official sources checked: https://nextjs.org/docs/app/getting-started/installation,
https://ui.shadcn.com/docs/installation/next, https://vercel.com/font and npm package metadata.
The pinned ui-ux-pro-max skill recommends data-dense dashboards; its marketing conversion
pattern did not match this product and was discarded after one narrower query. Kavrigo's
colors, typography, accessibility and paper-mode invariants take precedence.
