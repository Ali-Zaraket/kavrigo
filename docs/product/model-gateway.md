# Model gateway — local step 8

Implements ADRs 0010, 0011 and 0022 in `kavrigo-engine/libs/model-gateway`. It is a local,
provider-neutral library, with no HTTP endpoint and no private exchange or model credential.

Trusted service code registers:

- workspace daily cost/call and rolling-minute quotas;
- immutable agent-version access (`AgentAccess.from_version` uses AgentSpec model policy);
- profile routes with resolved model, versioned prices and hard token/timeout limits;
- versioned prompt keys with exact input and output Pydantic types;
- a local provider, budget ledger and optional OTel instrumentation.

Persist `registered_prompt_hash(definition)` on the AgentVersion; it includes the fixed
untrusted-data boundary as well as the registered prompt text. Access built with `from_version`
refuses a prompt whose hash differs from that immutable version.

Submit `ModelRequest` with verified scope, decision ID, idempotency key, prompt key, profile and
input JSON. The JSON is validated into the registered input type before it reaches a provider.
Use `structured(request, DecisionProposal)` for analysis, or `embed(EmbeddingRequest(...))`
with registered `EmbeddingInput`/`EmbeddingOutput`. A successful result has a typed output and
the existing `ModelCallRecord`. `UNKNOWN`/`NO_TRADE` is successful. No result grants risk approval.

Errors are `GatewayError` with a stable `FailureCode` and, if dispatch occurred, a call record.
Never log raw provider exceptions or Pydantic validation errors. `cost_is_reservation=true`
means usage is unknown and the cost cap remains reserved; it is not an invoice or zero spend.

Persist the returned output JSON with its record as `RecordedResponse` in tenant-authorized
storage. `replay()` checks request/prompt/schema/route/output hashes, scope and model identity,
then revalidates the output without calling a provider or consuming quota. Exact model pinning
is required for backtest calls. `ReproducibilityBundle.with_model_calls()` binds actual records;
the pre-runtime zero-decision backtest remains unchanged and still has no strategy.

The mock consumes scripted JSON/replies/errors and counts UTF-8 bytes as mock tokens. Configured
prices in fixtures are synthetic, not market prices. The suite needs no external key.

Observability: `model_call_finished`/`model_call_rejected` logs, OTel generation/embedding spans,
call/token counters and latency histogram. Tenant IDs are trace/log context, not metric labels.
Cost is an exact decimal string on the trace/record, never a floating-point accounting metric.
Prompt content, model output and exception bodies are omitted. Exporters must be configured by
the application after privacy/retention review. Tracing is not the audit ledger.

Paid routing is blocked by construction until durable reservations/idempotency, account setup,
verified provider adapter semantics and retention/export policy are supplied. See HANDOFF §5.
