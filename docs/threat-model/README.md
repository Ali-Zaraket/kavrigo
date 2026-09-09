# Threat models

One document per trust boundary. Use `template.md`. A threat model is required before a
component that handles credentials, untrusted content, tenant data, or execution ships.

| Boundary | Document | Status |
|---|---|---|
| Untrusted content → decision agent | [untrusted-content.md](untrusted-content.md) | Draft |
| Decision / allocation → risk / paper handoff | [deterministic-risk.md](deterministic-risk.md) | Local; independent review pending |
| Execution and credentials | *not started — blocked on the restricted repository* | — |
| Tenant isolation | *not started* | — |
| Supply chain | *not started* | — |

Baselines: OWASP Top 10 for LLM Applications, NIST AI RMF and its generative-AI profile.
