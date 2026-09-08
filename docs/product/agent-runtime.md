# Agent runtime — local step 10

`LocalAgentRuntime` in `services/agent-runtime` implements [ADR 0024](../adr/0024-local-agent-runtime.md).
It produces structured decisions and inert portfolio allocations. It has no order or exchange
write capability and refuses non-local startup.

Trusted application code registers `RuntimeRegistration`: an immutable `AgentVersion`, explicit
`RuntimePolicy` and optional model pin. Register `analysis_prompt(profile)` with the gateway
and use `AgentAccess.from_version` for per-decision model budgets. Newly created API versions
pin the shared v2 prompt; old scaffold versions require a new version, never an in-place edit.

`evaluate(EvaluationRequest)` takes authorized workspace/version context, an idempotency key,
one configured horizon, a frozen market/portfolio snapshot and its evidence. Feature hashes
follow the existing feature engine; `snapshot_hash()` defines the runtime snapshot hash.
The service validates these hashes, publication/availability timing, enabled packs, valuation
and reconciliation before dispatch. It reads `NetworkContextProvider.frozen_contexts()` once;
`FrozenNetworkContexts` is the local adapter and `network_hash()` hashes those immutable records.

The deterministic scanner ranks configured feature threshold hits. Only selected candidates
receive a model call. Missing evidence or unusable network context abstains. Models must search
for contradictions in supplied evidence; the service checks returned references, horizon,
currency and cost shape, then binds all authoritative IDs and actual model-call records.
Abstention is successful. Reference validation does not establish factual truth; golden semantic
evals remain necessary.

`EvaluationResult` records the request/runtime-policy hashes, contexts, decisions and actual
calls, including cancelled calls recovered through the gateway's read-only `record_for()`.
Retries return cloned prior results; changed inputs under a key conflict. Daily/interval/cycle
bounds prevent unlimited evaluation. State is local and bounded, with no restart persistence.
Cancellation and timeouts are terminal under that key and give no partial allocation.

The portfolio pass ranks competing proposals and reduces them using available cash, configured
overlap groups, exposure/allocation caps and an explicit fee buffer. It does not assume a
stablecoin is USD, estimate empirical correlations, spend unfilled sale proceeds or approve
risk. Only USD-quoted spot valuations are supported; pending orders and unknown state block
allocation. Amounts round down at 12 decimal places; venue size/tick validation comes later.

Next, the risk engine must independently validate each unapproved intent against trusted current
market/account/policy state. Runtime allocations are never evidence of risk approval.

No Temporal scheduling, persistent decision/evidence store, network collector, hosted model
provider, HTTP evaluation endpoint or Nautilus strategy is deployed by this slice. The worker
remains a skeleton until step 13. Backtest registration requires a model pin, but actual
recorded-model replay and market-to-strategy wiring must be completed before reporting a
meaningful model-backed Nautilus backtest.
