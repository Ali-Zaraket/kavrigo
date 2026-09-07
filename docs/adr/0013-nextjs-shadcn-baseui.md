# ADR 0013: Next.js with shadcn/ui on Base UI for the web client

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §16.1, §30.8

## Context

The product is a dense, keyboard-first, information-heavy terminal-style application that must also serve marketing pages, and must be accessible (WCAG 2.2 AA) with an excellent light and dark theme.

## Options considered

1. **Next.js + shadcn/ui (Base UI) + Tailwind + TanStack + Lightweight Charts.**
2. **A bespoke SPA component system** — maximum control, far slower to reach accessible, consistent density.
3. **A commercial enterprise component suite** — fast, wrong aesthetic and licensing overhead.

## Decision

Option 1: Next.js on the current Active LTS with security patches applied, React 19.x, strict TypeScript, Tailwind, shadcn/ui with Base UI primitives, TanStack Query/Table, TradingView Lightweight Charts, Zod validation and a generated OpenAPI client. Exact versions are resolved and pinned when the web app is scaffolded, against current release notes rather than recollection.

## Security and compliance impact

A generated API client reduces the chance of a hand-written call omitting workspace scoping. Never encode gain/loss or risk by colour alone, and paper/live status must be impossible to confuse (§31).

## Consequences

Easier: accessible dense UI at speed. Harder: framework upgrade cadence must be tracked deliberately.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
