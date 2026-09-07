# Threat model: <boundary>

- **Status:** Draft | Reviewed | Accepted
- **Date:** YYYY-MM-DD
- **Owner:** <role>
- **Components in scope:** <services, data stores, external systems>

## Trust boundary

What crosses it, in which direction, and which side is trusted. A diagram if it helps.

## Assets

What an attacker wants: credentials, tenant data, model budget, execution capability,
market data licences, audit integrity.

## Actors

Anonymous internet, authenticated tenant user, another tenant, a compromised provider,
a malicious content author, an insider, a compromised dependency, a coding agent.

## Threats

| # | Threat | STRIDE / OWASP LLM | Impact | Likelihood | Mitigation | Residual risk |
|---|---|---|---|---|---|---|
| 1 | | | | | | |

## Mitigations that must be tested, not assumed

List the automated tests that prove each load-bearing mitigation holds.

## Detection

What signal fires if the mitigation fails, and where it is routed.

## Open items

Anything unresolved, with an owner and a date.
