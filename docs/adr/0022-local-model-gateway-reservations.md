# ADR 0022: Local model gateway reservations and recorded replay

- **Status:** Accepted
- **Date:** 2026-09-08
- **Deciders:** Engineering, within the paper-first bootstrap scope
- **Spec reference:** §13.2–13.5, §14, §15.2, §20, §25, §46; ADRs 0010 and 0011

## Context

Step 8 needs a provider-neutral model boundary before news extraction and agent runtime. No
model or Langfuse account has been provisioned. Implementing a commercial provider from a
remembered API shape, or giving it process-local spend accounting, would misrepresent safety.

## Options considered

1. Direct SDK calls with post-response cost checks: cannot prevent concurrent overspend and
   allow implicit SDK retries/fallbacks to change provenance.
2. A typed single-attempt gateway, registered prompts/schemas, local scripted provider and
   atomic reservations; explicitly refuse paid/non-local deployment until durable accounting.
3. Add a hosted gateway now: needs accounts, verified commercial configuration and retention
   policy; does not remove the need for our own call record and validation.

## Evidence

Verified 2026-09-08:

- [Pydantic JSON validation](https://docs.pydantic.dev/latest/concepts/json/): JSON validation
  has different coercion semantics and supports partial parsing. We require a complete object,
  reject duplicate keys/non-finite numbers, then validate against the registered Pydantic type.
- [Python JSON](https://docs.python.org/3.13/library/json.html): `object_pairs_hook` and
  `parse_constant` provide those checks. JSON decimal numbers remain floats so `ExactDecimal`
  rejects them for money; authoritative decimal amounts must arrive as strings/integers.
- [Python cancellation/timeouts](https://docs.python.org/3.13/library/asyncio-task.html#timeouts):
  timeouts use cooperative cancellation. A client timeout is not proof that remote billing
  stopped. Retain the full reservation when usage is unknown and propagate caller cancellation.
- [Langfuse OpenTelemetry integration](https://langfuse.com/integrations/native/opentelemetry)
  documents generation/embedding, model and usage attributes. Native OTel supports our hooks
  without adding a second tracing SDK or exporting prompts. OTel API/SDK 1.44.0 exercised locally.
- [OpenAI structured outputs reference](https://platform.openai.com/docs/api-reference/responses-streaming/response/refusal?lang=python)
  explicitly distinguishes refusal/incomplete responses and a supported subset of JSON Schema.
  These are internal failure categories here; no vendor request/signature is implemented.
  The guide URL returned a navigation-heavy page, so it was not used to infer an API shape.

## Decision

Option 2 implements the smallest local slice of ADR 0010. All routes name profiles and pin
provider/model/pricing/limits. There is one provider attempt, no retry/fallback/tool execution.
Prompts and input/output types are code-registered. The provider receives only the registered
prompt, validated input JSON, output schema and token limit, not tenant/account objects.

`DecisionProposal` contains the existing decision fields owned by the model. `AgentDecision`
adds server-owned identity/time/call provenance. The existing `ModelCallRecord` gains optional
scope, hashes, outcome and uncertainty fields; older records remain readable. Backtest bundles
can bind the actual call records instead of a caller-invented resolved model string.

Reserve worst-case cost before dispatch, atomically across workspace/agent daily limits and
the decision's total call/cost/time limits. Use integer picodollars with upward rounding;
prices are explicit versioned configuration, never presumed vendor prices. Rate limits are
rolling 60-second call counts, not guessed provider quotas. Finalization settles known usage;
unknown usage retains its upper bound. Invalid output still costs tokens. Retries with the
same workspace/idempotency key reuse a validated record or its terminal failure; a changed
request conflicts, and an in-flight duplicate returns `in_progress`. Capacity exhaustion
refuses further admission instead of evicting spend/idempotency state.

Local accounting and the mock provider require `environment=local`; network providers are
rejected. This is not a change to the eventual PostgreSQL authoritative-state architecture.
Paid/distributed routing requires a PostgreSQL reservation ledger with process-crash recovery,
tenant authorization/RLS, reconciliation and durable idempotency. Valkey may rate-limit but
must not become the billing ledger. No account provisioning or provider billing is attempted.

## Security and compliance impact

No credential lookup, filesystem reader, environment lookup, vendor SDK, URL fetcher, exchange
tool or execution dependency exists in the gateway. Registered input schemas forbid extras;
credential-shaped fields/text are rejected without echoing them. This screening is defense in
depth, not a claim that regex can recognize every unlabelled secret. The deployment's lack of
exchange credentials remains the primary security boundary. Caller code must supply verified
workspace access; this library is not an authentication service or a public JSON proxy.

Traces/logs contain bounded operational metadata and hashes, not raw inputs/outputs or provider
exception bodies. OTel automatic exception recording is disabled. Langfuse export and retention
are not configured. Recorded responses belong in our tenant-authorized immutable artifact
store; a content hash proves consistency, not authenticity of an untrusted replacement record.

## Operational impact

Mock accounting is deterministic but has no relation to a vendor tokenizer or invoice. A
provider adapter must bound all input tokens including prompts/schemas, apply transport and
token limits, report usage, and disable its own retries/tools. No production hard cost guarantee
is claimed for process-local state. Non-cooperative provider code cannot be forcibly stopped by
asyncio; real adapters need transport deadlines and uncertain-call recovery.

## Migration and rollback

Additive call-record/bundle fields require no database migration. The new proposal base keeps
the flattened `AgentDecision` JSON shape. Remove the gateway consumer to roll back; retained
call records still validate. Before paid routing, replace the local ledger behind an audited
durable implementation and re-run concurrency/crash/replay tests. Do not relax the local gate.

## Consequences

News/runtime can exercise schema validation, budget errors and reproducible replay offline.
Hosted providers, SDK orchestration, durable billing and trace export remain explicit next
deployment work, rather than silently operating with inadequate persistence or privacy controls.
