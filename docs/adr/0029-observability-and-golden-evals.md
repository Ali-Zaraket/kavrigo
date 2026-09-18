# ADR 0029: Content-free telemetry and local golden evaluations

Status: accepted for local bootstrap, 2026-09-16.

Implements MASTER_BUILD_SPEC sections 13.4 and 26 and build step 15. Existing domain
instrumentation remains vendor neutral. Service entry points own OTel SDK providers and
bounded exporters; a shared library filters exported spans and metric dimensions. Export
is off by default, with local console or explicitly configured OTLP/HTTP targets. Langfuse
receives only model spans through its documented OTLP interface. It is never a trade ledger.

Use an explicit attribute allowlist, fixed span names, no exception events, no source bodies,
no prompts/completions, no raw URLs or tenant/user identifiers. Resource fields are constructed
explicitly rather than importing environment metadata. Model replay does not report a second
generation's token/cost consumption. Reserved unknown costs remain distinct from actual cost.
SDK queues and export timeouts are bounded; telemetry loss cannot grant trading permission.

Versioned synthetic golden cases exercise the actual news pipeline and model gateway offline.
The report records dataset, prompt and schema hashes, code revision and installed versions.
These are deterministic boundary regressions using scripted model replies, not evidence of
paid-model accuracy, investment edge or complete injection protection. Hosted evaluation and
retention/access policies require provider accounts and reviewed configuration.

Alternatives: automatic content capture risks exporting credentials/licensed content; treating
telemetry as authority risks losing financial state when sampled or unavailable. A Langfuse SDK
inside domain components creates unnecessary vendor coupling. Rollback disables exporters and
removes additive instrumentation/evals without changing authoritative account state.

Official references checked 2026-09-16:
- https://opentelemetry.io/docs/languages/python/exporters/
- https://opentelemetry.io/docs/languages/python/instrumentation/
- https://langfuse.com/integrations/native/opentelemetry

Use Langfuse's HTTP `/api/public/otel/v1/traces` endpoint and ingestion-version 4 header.
No hosted project is provisioned or contacted by the default local configuration.
