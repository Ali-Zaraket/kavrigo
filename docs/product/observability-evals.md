# Observability and synthetic golden evaluations

Implements the local step 15 slice, ADR 0029. No hosted Langfuse account or monitoring
backend is assumed. Diagnostics are never financial authority, and export can be lost.

## Service telemetry

The API and Temporal worker process entry points configure OpenTelemetry once. Existing
gateway/news/runtime/risk/paper/account/workflow instrumentation feeds the configured SDK.
API instrumentation records route templates, methods, status and duration, including failures.
Raw path/query values, HTTP headers, bodies and exception messages are excluded. Unknown
routes share one `unmatched` label. Request IDs are bounded before being echoed/logged.

Set `KAVRIGO_TELEMETRY` to:

- `off` (default): no telemetry export. Application logs and durable audit remain active.
- `console`: local JSON OTel traces/metrics in service output.
- `otlp`: explicit `KAVRIGO_OTLP_ENDPOINT` collector base URL; `/v1/traces` and `/v1/metrics`
  are appended. HTTPS is required except for the named local collector/loopback hosts.

For a local smoke check in PowerShell, set `$env:KAVRIGO_TELEMETRY='console'` and run
`docker compose -f kavrigo-infra/local/docker-compose.yml up -d --build api engine-worker`.
Keep the destination host port overrides documented in MACHINE_HANDOFF.md. Restore `off`
and recreate those services after inspection. This changes no databases or volume contents.

Trace queues hold at most 1,024 general spans and 512 model spans; batches are 128/64,
with two-second HTTP export timeouts. Metrics export every 30 seconds. Exporter failures
do not authorize or retry a financial command. Telemetry queues have no durability guarantee.
SDK shutdown drains bounded pending work; do not treat a telemetry acknowledgement as a
database commit. Incoming arbitrary baggage is not imported by the API middleware.

Export filters allow only registered span names/scopes and explicit metadata keys. They
remove tenant/user IDs, exception events, links, status descriptions, trace-state and
arbitrary resource/scope metadata. Metric views restrict instrument names and dimensions.
Exemplars are disabled because their filtered attributes can retain discarded dimensions.
These filters protect against accidental content capture, not malicious application code
deliberately placing secrets into a permitted field. Review changes to the allowlists.

## Langfuse

The model gateway emits generation/embedding type, registered model, prompt hash, tokens,
outcome and cost metadata. The isolated Langfuse exporter receives model spans only.
Cached responses export as ordinary spans without model/usage/cost generation fields;
unknown cost reservations do not export usage/cost as an actual charge. The original
decimal cost remains in authoritative records. No prompt body or completion is exported.

After the operator provisions an approved project/region, supply all three values at runtime:

- `KAVRIGO_LANGFUSE_ENDPOINT`: full approved URL ending `/api/public/otel/v1/traces`.
- `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`: project credentials, never source files.

Enable `console` or `otlp`; partial or disabled Langfuse configuration refuses startup.
OTLP HTTP uses Basic authentication and `x-langfuse-ingestion-version: 4`. Generic OTel
header environment variables are not imported into these explicitly configured exporters.
No hosted request is made by tests: a loopback receiver decodes the real Protobuf payloads
and verifies endpoint routing, authentication format, redaction and replay cost handling.
Project retention, RBAC, region, dashboards and alert delivery remain operator release work.
Repository prompt hashes remain canonical; there is no claim that a prompt was published
to Langfuse prompt management.

## Golden evaluations

`kavrigo-research/datasets/golden-v1.json` contains 31 authored synthetic cases. It contains
no provider content and is suitable for repository distribution. Categories cover extraction
support/entity/authority checks; instruction overrides in visible/hidden/encoded markup;
and structured decision abstention, exact money, contradictory evidence, invalid JSON,
unauthorized tool/risk/tenant fields, provider failures and sensitive input refusal.

From the repo root (with workspace dependencies installed):

```sh
PYTHONPATH=kavrigo-research python -m kavrigo_evals \
  --code-revision "$(git rev-parse HEAD)" --output .local/golden-report.json
```

Use `--dirty` when evaluating uncommitted code. PowerShell uses
`$env:PYTHONPATH='kavrigo-research'` before the equivalent Python command.
The report contains case IDs, observed status and boolean checks, dataset/prompt/schema
hashes, revision, fixed clock, seed and dependency versions. No article/model body is copied
to it. Any failed check produces a nonzero CLI exit. CI retains the report as an artifact.

Each case invokes production gateway/news code with scripted model replies. This proves
bounded regression behavior, not a model's ability to generate those replies. A passing
injection corpus is not universal protection. Broader held-out corpora, paid-provider
quality comparison, runtime strategy evals and online drift evaluation remain outstanding.

## Coverage and operations

Implemented: API request outcomes; existing model token/latency/outcome metrics; extraction
outcomes/source age; runtime decisions/abstention; risk rejections; paper accounting events;
durable commands and workflow stages. SDK exporters are activated by the two service entry
points. Local library callers must inject providers or use a service bootstrap.

Pending: browser/Next server trace export and cross-service trace propagation; real ingestion
transport metrics; database pool/queue saturation; hosted dashboards/alerts and measured SLOs.
The web facade already emits content-free status/duration logs. No new browser telemetry is
sent to a third party. Infrastructure exporters should be added with the corresponding real
service, not populated with synthetic health or invented latency targets.

Triage API failures by route/status and bounded request ID; triage model failures by outcome
and prompt hash. Inspect the authoritative run/account receipts before retrying any command.
If export fails, inspect collector reachability/configuration without logging credentials;
disable only the exporter to restore diagnostics stability. Never reset a ledger, release a
risk reservation, or relax freshness to make an observability dashboard green.

Official references: [OTel Python exporters](https://opentelemetry.io/docs/languages/python/exporters/)
and [Langfuse OTLP](https://langfuse.com/integrations/native/opentelemetry), checked 2026-09-16.
