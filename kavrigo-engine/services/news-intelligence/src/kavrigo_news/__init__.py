"""News intelligence: local typed extraction, source provenance and point-in-time evidence."""

from kavrigo_news.contracts import (
    Entity,
    ExtractionInput,
    FeedAdapter,
    FeedBatch,
    NewsExtraction,
    NewsRecord,
    NewsResult,
    NewsStatus,
    RawArticle,
    SourcePolicy,
)
from kavrigo_news.feeds import ScriptedFeed
from kavrigo_news.pipeline import NEWS_PROMPT, LocalNewsPipeline, available_evidence

__all__ = [
    "NEWS_PROMPT",
    "Entity",
    "ExtractionInput",
    "FeedAdapter",
    "FeedBatch",
    "LocalNewsPipeline",
    "NewsExtraction",
    "NewsRecord",
    "NewsResult",
    "NewsStatus",
    "RawArticle",
    "ScriptedFeed",
    "SourcePolicy",
    "available_evidence",
]
