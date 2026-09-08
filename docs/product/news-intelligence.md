# News intelligence — local step 9

`kavrigo-engine/services/news-intelligence` implements the scripted-feed to frozen-evidence
slice in [ADR 0023](../adr/0023-local-news-evidence.md). It uses no provider key or external feed.

Trusted service code registers `SourcePolicy` and `Entity` objects, grants `EXTRACT_FAST` access
in the model gateway, and registers `NEWS_PROMPT`. The source and mapping configuration is
versioned/hashed. Source quality is explicitly configured, not inferred from an article's claims.
The package constructor refuses non-local environments; its licensing contract permits only
synthetic fixtures.

`FeedAdapter.read()` returns at most 32 `RawArticle` objects in `FeedBatch`. `ScriptedFeed` is the
local implementation. `LocalNewsPipeline.collect(feed, authorized_scope)` or `process()` returns
`NewsResult`: extracted, duplicate, quarantined, unavailable, in-progress or capacity. Callers
must authenticate/authorize the scope; this library is not an HTTP authentication boundary.

The pipeline checks publication/arrival times and source URLs, extracts bounded text from HTML,
normalizes Unicode and quarantines common instruction patterns. There is no HTML renderer or
URL fetcher. The model gets text and known entity IDs, and returns a closed `NewsExtraction`.
Its quote must occur in the sanitized text; each selected entity must occur in that quote via a
trusted alias. This checks support in the source, not factual truth. Downstream models must
continue treating every quote as untrusted data and receive no write tools.

`NewsRecord` carries `EvidenceItem` / `NewsEvent`, a content hash, transform/source hashes,
entity mapping and actual `ModelCallRecord`. It records publication, arrival and structured
availability separately. `available_evidence()` selects frozen records by workspace and
availability time; fresh extraction in backtest mode is refused. Records are cloned and
revalidated, including hashes, before replay. Storage authentication remains the caller's duty.

`envelope_for()` and `record_from_envelope()` round-trip the validated record through the
existing generic `news.event.normalized.v1` envelope with workspace tenancy and provenance.
There is no publisher or generated Protobuf binding yet.

Exact dedupe includes normalized headline and body within workspace/agent/version/transform.
It suppresses exact syndication across registered sources; a changed article at the same URL
is retained as new evidence. Different headlines, near-duplicates and independent corroboration
are not resolved. `novelty=1` labels exact uniqueness in this local corpus only. The primary
reference is populated only from trusted `OFFICIAL_PRIMARY` configuration; corroborating
references stay empty. A repost can neither upgrade source quality nor count as another source.

Failure never emits evidence. A repeated failed call in one decision reuses the gateway's
terminal outcome; a later decision can try again. Cancellation clears pending dedupe state.
Successful dedupe references are bounded in memory; exhaustion fails closed, restart loses
state. Durable checkpointing, provider collection and actual publication are deferred.

Tests cover scripted end-to-end extraction, source/tenant isolation, exact reposts and revisions,
future knowledge, content tampering, unknown entities, injection fixtures, unavailable models,
timeouts/cancellation, concurrent duplicates, capacity and metadata-only OTel/logging.
