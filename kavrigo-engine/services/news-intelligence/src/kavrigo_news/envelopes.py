"""Validated news.event.normalized.v1 payload in the existing generic envelope (§18).

No publisher or generated Protobuf binding is claimed. Raw articles are never included.
"""

from kavrigo_domain import EventEnvelope, EventSource, SourceKind, TenantScope
from kavrigo_news.contracts import NewsRecord

EVENT_TYPE = "news.event.normalized.v1"


def envelope_for(item: NewsRecord) -> EventEnvelope:
    record = NewsRecord.model_validate_json(item.model_dump_json())
    return EventEnvelope(
        event_id=record.event_id,
        event_type=EVENT_TYPE,
        tenant_scope=TenantScope(workspace_id=record.workspace_id),
        source=EventSource(
            kind=SourceKind.NEWS_FEED,
            provider=record.source_id,
            schema_version="1",
            transform_version=record.transform_version,
            license_ref=record.evidence.license_ref,
        ),
        event_time=record.evidence.observed_at,
        ingested_at=record.evidence.ingested_at,
        partition_key=record.workspace_id + ":news",
        correlation_id=record.model_call.decision_id,
        trace_id=record.model_call.trace_id,
        payload=record.model_dump(mode="json"),
    )


def record_from_envelope(item: EventEnvelope) -> NewsRecord:
    envelope = EventEnvelope.model_validate_json(item.model_dump_json())
    record = NewsRecord.model_validate(envelope.payload)
    if envelope != envelope_for(record):
        raise ValueError("news envelope provenance mismatch")
    return record
