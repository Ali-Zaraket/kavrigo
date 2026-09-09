# Contributing

## Before you change anything

1. Read `MASTER_BUILD_SPEC.md` and `AGENTS.md`.
2. State which requirement or ADR you are implementing in the commit or pull request.
3. Inspect existing contracts before adding new ones.
4. Verify external API/library behaviour against current official documentation. Do not invent
   provider fields or endpoints; use mocks until credentials exist.

## Definition of done

Per `MASTER_BUILD_SPEC.md` §61, a change is not done until it has: documented behaviour, typed
contracts, tests, tenant scoping, authorization, observability, error states, stale-data
behaviour where relevant, an audit event if high impact, docs, no secrets, safe migrations, and
a security review appropriate to its impact.

## Pull request format

```markdown
### Implemented
### Contracts
### Tests
### Security/risk
### Observability
### Remaining
```

Do not describe a change as "production ready" merely because it compiles.

## Local checks

```bash
make setup
make check     # format check + lint + typecheck + tests
```

`pre-commit` runs formatting, linting and secret scanning:

```bash
uv run pre-commit install
```

## Commit and branch rules

- Current bootstrap workflow, explicitly requested by the user on 2026-09-09: work on
  `main`, commit each completed slice separately, and use ordinary non-force pushes.
  This supersedes the earlier work-branch/PR workflow for this repository. Do not change
  remote branch protections or bypass a server-side rejection.
- Keep commits small and auditable. Use pull requests when separately requested.
- Changes to risk, execution, credentials, auth, billing entitlements, tenant isolation or
  schema migrations require the stricter reviewers listed in `CODEOWNERS`.
- Architecture changes require an ADR (`docs/adr/0000-template.md`) committed with the change.

## Things that are never acceptable

- Committing secrets, exchange credentials, or private keys.
- Binary floats for authoritative money or quantity.
- A model output that becomes an exchange command without deterministic risk evaluation.
- Bypassing risk controls "for a demo".
- Live-execution shortcuts, or code that weakens KYC/age/sanctions/jurisdiction controls.
- Treating internet, news or MCP content as instructions.
