# API conventions

Applies to the control-plane REST API (`MASTER_BUILD_SPEC.md` §49, `AGENTS.md` § API principles).
REST/OpenAPI only — no GraphQL in V1 (ADR 0013 context).

## Transport and shape

- **REST/OpenAPI** for the control plane; **SSE** for run/event logs; **WebSocket** for live
  market UI updates. Protobuf is for internal stream contracts, not the public API.
- Versioned path prefix: `/v1/...`. A breaking change means `/v2`, never a silent change.
- JSON only. `application/json; charset=utf-8`.

## Types

- **Timestamps**: UTC, RFC 3339 / ISO 8601, always with an explicit offset (`2026-03-01T12:00:00Z`).
  Naive timestamps are rejected, not guessed.
- **Money and quantity**: JSON **strings** holding exact decimals, with the unit alongside —
  `{"amount": "1234.56", "currency": "USDT"}`. Never a JSON number: IEEE-754 double cannot
  represent every decimal a venue can, and a client that parses it as a float silently loses
  precision (`AGENTS.md` domain rule 6).
- **Instruments**: canonical ids, never bare tickers — `"BTC-USDT.BINANCE"`, optionally suffixed
  with a contract class (`":perpetual"`). `"BTC"` is not an instrument.
- **Enums**: lowercase snake_case strings from a closed set. Clients must tolerate unknown
  members appearing in future versions.

## Mutations

- **Idempotency is required** on every state-changing request: `Idempotency-Key` header, stored
  with the response for at least 24 hours. A replay returns the original result; a reused key
  with a different body returns `409` with code `idempotency_key_reused`.
- **Optimistic concurrency** via `If-Match`/`ETag` where a resource can be edited concurrently.
- Editing an agent creates a **new version**; it never mutates the configuration that produced
  historical decisions.

## Tenancy

- Every request resolves a verified `workspace_id` from the authenticated session, never from a
  client-supplied header alone. Backend scoping plus PostgreSQL RLS (`MASTER_BUILD_SPEC.md` §20).
- Cross-workspace references are rejected with `403`/`forbidden`, not `404`, once the caller is
  authenticated for some workspace — except where existence itself is sensitive, in which case
  `404`/`not_found` is used consistently for both cases.

## Pagination

Cursor-based only. Offset pagination over append-heavy data returns duplicates and gaps.

```json
{ "items": [], "next_cursor": "opaque", "has_more": true }
```

`limit` defaults to 50, maximum 200. Cursors are opaque and must not be constructed by clients.

## Errors

Every error returns the same body with a stable machine-readable code:

```json
{
  "code": "workspace_required",
  "message": "A workspace context is required.",
  "request_id": "…",
  "details": {}
}
```

- Codes are added, never repurposed. See `ErrorCode` in `kavrigo_api/errors.py`.
- `message` is safe to display. Internal exception text is logged, never returned.
- Every response carries `X-Request-Id`, echoed from the request when supplied.

| Status | Typical code |
|---|---|
| 400 | `validation_failed` |
| 401 | `unauthenticated` |
| 403 | `forbidden`, `workspace_required`, `live_trading_disabled` |
| 404 | `not_found` |
| 409 | `conflict`, `idempotency_key_reused` |
| 429 | `rate_limited` |
| 503 | `upstream_unavailable` |

## Freshness

Any response carrying market-derived data states its age. The UI must be able to render `LIVE`,
`12s old`, `Delayed`, `Reconnecting`, `Stale` or `Provider unavailable` (`MASTER_BUILD_SPEC.md`
§31) from the payload — never from a client-side guess.

## Documentation and clients

- OpenAPI is generated from the code and is the source of truth for the TypeScript client.
- No database model is ever serialised directly into a response.
- Interactive docs are disabled in production-like environments.
