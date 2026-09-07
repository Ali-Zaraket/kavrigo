# Threat model: untrusted content → decision agent

- **Status:** Draft
- **Date:** 2026-09-04
- **Owner:** Architecture / Security
- **Components in scope:** feed collectors, fetcher, sanitizer, structured extraction, evidence
  store, agent runtime, model gateway, MCP research tooling.
- **Spec reference:** `MASTER_BUILD_SPEC.md` §14, §7.12, §42.

## Trust boundary

Everything retrieved from the internet — articles, social posts, provider payloads, MCP tool
results — is **data**, never instruction. It crosses into the platform through a one-way
pipeline and reaches a decision agent only as a validated, frozen `EvidenceItem`.

```text
web / news / provider / MCP
  → fetcher (no execution, no redirects to internal hosts)
  → sanitizer + provenance capture
  → structured event extraction (isolated model call, schema-validated output)
  → corroboration / source-quality scoring
  → frozen EvidenceItem
  → decision agent
```

## Assets

Execution capability, model budget, tenant data, audit integrity, and the correctness of the
risk decision itself.

## Threats

| # | Threat | Class | Impact | Mitigation | Residual risk |
|---|---|---|---|---|---|
| 1 | Prompt injection in an article body instructing the agent to buy | OWASP LLM01 | Unjustified order intent | Content never enters a system or tool-policy position; extraction output is schema-validated; the decision model receives structured evidence, not raw text; deterministic risk sizes and can reject the result regardless | Model may still weight a fabricated claim; corroboration and source-quality scoring reduce, not eliminate |
| 2 | Injected instruction attempting to change risk policy or reveal secrets | LLM01 / LLM06 | Policy bypass, credential disclosure | Risk policy is deterministic code outside the model (ADR 0004); no credential is reachable from any agent tool (ADR 0017); tool allowlist is typed and read-only | Low; enforced by topology, not by prompt |
| 3 | Tool poisoning via a compromised MCP server | LLM05 / supply chain | Corrupted evidence, exfiltration attempt | MCP is research-path only (ADR 0005); MCP output is sanitized like any untrusted content; no write-capable or credentialed MCP connection exists | Depends on provider security; treat all MCP output as hostile |
| 4 | Fabricated or spoofed "primary source" | Data integrity | Bad decision on false evidence | Primary-source resolution, source classes, corroborating-source references, novelty and certainty scoring recorded on every event | Real; a convincing fake wire story remains possible — hence position sizing and risk limits |
| 5 | Syndication flooding to manufacture apparent corroboration | Data integrity | Inflated importance/novelty | Deduplication by embedding and canonical-source resolution before corroboration counting | Partial |
| 6 | Content designed to trigger unbounded tool loops or huge contexts | LLM10 / cost | Denial of wallet | Per-profile token/call/timeout caps and per-workspace budgets (§46); scanner prefilter limits how often deep reasoning runs | Bounded by budget enforcement |
| 7 | SSRF via a fetched URL pointing at internal infrastructure | Infrastructure | Internal disclosure | Fetcher egress allowlist, no redirects to private ranges, no credentials on the fetch path | Low |
| 8 | Injection persisted into stored evidence and replayed in a later decision or backtest | Persistence | Repeated bad decisions | Evidence is immutable and content-hashed; detections are logged with the evidence id; suspicious-instruction detection is a recorded signal | Requires a re-scan capability for stored evidence |

## Mitigations that must be tested, not assumed

- A golden eval set of injection attempts must produce zero policy-affecting outputs.
- Extraction output that fails schema validation must be rejected, never coerced.
- A property test must show that no `AgentDecision`, whatever its content, can reach a venue
  without a deterministic risk approval.
- The agent tool registry must be asserted read-only in tests.

## Detection

Prompt-injection detection count, schema-failure rate, abstention rate, per-agent tool-call and
cost distribution, evidence dedupe ratio, and source-class mix — all exported as metrics (§26.2).

## Open items

- Re-scan procedure for previously stored evidence when a new injection pattern is found.
- Source-quality scoring methodology and its evaluation set.
- Fetcher egress allowlist ownership.
