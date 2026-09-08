# ADR 0023: Local news extraction with service-owned provenance

- **Status:** Accepted
- **Date:** 2026-09-08
- **Deciders:** Principal engineering agent
- **Spec reference:** `MASTER_BUILD_SPEC.md` §§7.12, 14, 18, 42; build step 9

## Context

The existing domain has `NewsEvent` and `EvidenceItem`, and step 8 supplies a bounded local
model gateway. No news provider schema, commercial rights or collector infrastructure is
configured. Article publication time cannot establish when extracted evidence became knowable.
Model JSON must not assign source authority or inflate corroboration with syndicated copies.

## Options considered

1. Accept full `NewsEvent` JSON from a model. Small, but gives untrusted output ownership of
   timestamps, primary-source references and quality.
2. Add network collectors and semantic dedupe now. Requires provider verification, licensing,
   durable checkpoints and evaluated similarity/corroboration policies that do not yet exist.
3. Use a synthetic feed interface, exact dedupe and restricted extraction schema, then bind
   service-owned provenance. Gives a testable slice without pretending a collector is deployed.

## Evidence

Official documentation fetched and reviewed 2026-09-08:

- [Python HTMLParser](https://docs.python.org/3.13/library/html.parser.html): text callbacks,
  character-reference conversion and the absence of automatic closing-tag matching. Only the
  longstanding `convert_charrefs` argument is used; host Python is 3.13.5.
- [Python Unicode database](https://docs.python.org/3.13/library/unicodedata.html): NFKC and
  character categories used to normalize text and remove hidden format/control characters.
- [Python URL parsing](https://docs.python.org/3.13/library/urllib.parse.html): parsing is not
  validation; the pipeline separately checks schemes, authority, ports and exact allowed hosts.
- [OTel Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/):
  existing step 8 tracing and metric interfaces reused with in-memory exporters in tests.

No third-party feed format, endpoint, source rating, provider limit or commercial right is
invented. Fixture quality scores are explicit test configuration, not researched source ratings.

## Decision

Add `services/news-intelligence` using the existing domain contracts. `NewsExtraction` owns
classification scores, allowlisted entity IDs and an exact supporting quote. The service owns
source class/quality/license, URL, publication/arrival/availability times, asset/instrument
mapping, event identity and model-call provenance. Certainty is capped by trusted source quality.

Normalize HTML to text only, remove hidden markup, scan raw and visible text for common
instruction patterns, and quarantine suspicious content before dispatch. Validate the returned
quote and entity references against sanitized text. These are defense layers, not proof of
truth or complete prompt-injection prevention. No model tools or permission-changing fields exist.

Exact normalized headline/body copies are deduplicated within workspace/agent/version and
transform configuration, including copies from different registered sources. Changed text at
the same URL is new evidence. Reposts do not become corroboration. `novelty=1` means only
previously unseen exact text in this local corpus, not novel information in the market.
Corroborating references remain empty until a verified independent-source resolver exists.

Evidence becomes available at completed extraction time, never article publication time.
Fresh extraction in backtest mode is refused: backtests filter authenticated frozen records
by `evidence.ingested_at`. Every record hashes its classification, provenance, mapping, quote
and actual model-call record; consumer validation detects accidental alteration.

Use the existing generic `EventEnvelope` carrier with validated `NewsRecord` payload on
`news.event.normalized.v1`. No new generated Protobuf binding or bus publisher is claimed.

## Security and compliance impact

Construction refuses non-local environments. Sources require an explicit synthetic-fixture
license reference; no real feed redistribution is enabled. The service does not fetch URLs,
resolve DNS, follow links, access secrets, import vendor SDKs or construct exchange requests.
Its input is internal: callers must authorize workspace/agent/version before supplying scope.
Hashes are integrity checks, not authentication. Recorded evidence must come from a trusted
store; caller-provided hashes cannot confer trust. Quotes remain untrusted data at the runtime.

No raw HTML is retained in results or telemetry. Result evidence contains a short quote under
the source's declared rights; real-provider quotation and retention policy remains a launch gate.

## Operational impact

One model attempt through the gateway; failure yields no evidence and is not marked as seen.
Concurrent duplicates return in-progress. Cancellation clears pending dedupe state, while the
gateway retains uncertain spend. Successful dedupe references are bounded and never evicted to
make room; exhaustion refuses new work. Restart loses local dedupe state. No durable collection,
offset acknowledgment, delivery guarantee or multi-process dedupe is promised.

OTel spans, outcome counts, source age and structured reason logs omit raw articles, quotes,
URLs and exception values. No hosted export is configured.

## Migration and rollback

Additive package, no database migration or domain field change. Remove its service registration
to roll back. Future verified feeds replace the adapter implementation; durable storage must
atomically persist evidence, source revisions and dedupe/checkpoints before collection is
enabled beyond synthetic local fixtures. A new transform hash is required when extraction,
mapping or prompt policy changes. Existing frozen evidence retains its old identity and time.

## Consequences

The runtime can consume attributable, bounded news evidence with tested point-in-time behavior.
Provider collection, near-duplicate detection, source-quality methodology, independent
corroboration and durable storage remain explicit work, rather than implied capabilities.
