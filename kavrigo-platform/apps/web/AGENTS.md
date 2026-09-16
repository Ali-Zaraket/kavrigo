# Kavrigo web

Apply the repository AGENTS.md, MASTER_BUILD_SPEC.md and ADR 0028 first.
Use the installed ui-ux-pro-max guidance while preserving Kavrigo's brand tokens.

Read `node_modules/next/AGENTS.md` and the version-matched documentation it references before
changing Next.js behavior. This application uses Next 16.3.4 App Router. Route params are
promises. Use server pages/layouts and small client boundaries for interaction. Never put
bearer tokens, tenant data or private environment values into static output or browser storage.

Regenerate src/lib/schema.ts from contracts/openapi.json with `pnpm generate:api`.
Backend monetary outputs remain strings; do not calculate ledger balances in JavaScript.
No raw engine payloads or account command proxy. No arbitrary external URL fetching.
Test membership changes, mode failure, idempotent retries, keyboard dialogs and both themes.
