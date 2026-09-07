# Security policy

## Reporting a vulnerability

Report suspected vulnerabilities privately. Do not open a public issue.

- Preferred: GitHub private security advisory on the affected repository.
- Email: `security@kavrigo.com` (to be provisioned with the domain; see `MASTER_BUILD_SPEC.md` §30.3).

Please include reproduction steps, affected component, and impact. We will acknowledge receipt
and keep you updated on remediation. Do not test against other tenants' data or against any
exchange account you do not own.

## Scope and security model

Kavrigo's security posture is defined in `MASTER_BUILD_SPEC.md` §24 and the threat models in
`docs/threat-model/`. Load-bearing invariants:

- **No secrets in model context.** LLMs never receive exchange credentials, and no agent tool
  can read them.
- **No model-authored exchange commands.** Agents emit a structured `AgentDecision`; only the
  deterministic risk engine can approve an `OrderIntent`, and only the isolated execution
  gateway can talk to a venue.
- **Risk cannot be overridden by prompt, tool output, or model output.**
- **Untrusted content is data, not instruction.** Web, news and MCP content is sanitized and
  converted to structured evidence before any decision agent sees it.
- **Fail closed.** Stale, unknown or unreconciled state rejects rather than trades.
- **Tenant isolation** on `workspace_id`, enforced in the backend and by PostgreSQL RLS.
- **Non-custodial.** The platform holds no user crypto and requires no withdrawal permission.

## Live trading

`LIVE_TRADING_ENABLED=false`. Live execution requires the full readiness checklist in
`MASTER_BUILD_SPEC.md` §47, including an external penetration test. Do not propose changes that
enable live execution outside that gate.

## Secrets

No production secret, exchange API key, or KMS decrypt capability may be placed in this
repository, in CI, in a local `.env`, or in any AI coding tool context. `.env.example` documents
required variables with placeholder values only. Secret scanning runs in pre-commit and CI.

The `kavrigo-execution-security` boundary is intentionally kept free of code until it is a
separate, access-restricted repository.
