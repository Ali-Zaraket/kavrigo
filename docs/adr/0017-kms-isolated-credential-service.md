# ADR 0017: KMS envelope encryption with an isolated execution-credential service

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Architecture
- **Spec reference:** `MASTER_BUILD_SPEC.md` §15.2, §24.3

## Context

Exchange credentials are the highest-value asset in the system. Any design where the API, the engine, the model gateway, or an LLM can read them makes every prompt-injection bug a potential fund-movement bug.

## Options considered

1. **Encrypted column in the application database** — convenient, and the application can always decrypt.
2. **A dedicated credential service with KMS envelope encryption, in a separate deployment and repository boundary, with an IAM role only that deployment can assume.**
3. **Client-side encryption with a user-held key** — strong, incompatible with unattended agent execution.

## Decision

Option 2. Plaintext exchange credentials are never visible to the browser, an LLM, the news pipeline, the model gateway, general application logs, or the analytics warehouse. Envelope encryption uses per-environment and per-tenant cryptographic context. Decrypt calls are audited. Emergency revocation and key rotation procedures are prerequisites for live mode.

## Security and compliance impact

This is the central blast-radius control of the platform. It is enforced by deployment topology and IAM, not by convention: the `kavrigo-execution-security` boundary is a separate access-restricted repository, and AI coding tools never receive its production secrets.

## Consequences

Easier: reasoning about credential exposure. Harder: a cross-boundary call on the execution path, and a second deployment to operate.

## Notes

This ADR records a decision made in `MASTER_BUILD_SPEC.md` during the 2026-09-04 research
pass. Vendor terms, pricing, licences and API behaviour change; re-verify against official
documentation before implementing against any external system, and supersede this ADR rather
than editing it if the decision changes.
