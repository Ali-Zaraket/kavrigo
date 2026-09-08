"""Synthetic local feed. No vendor endpoint, schema or redistribution right is assumed."""

from kavrigo_news.contracts import FeedBatch


class ScriptedFeed:
    def __init__(self, source_id: str, batches: tuple[FeedBatch, ...]) -> None:
        self.source_id = source_id
        self._batches = iter(batch.model_dump_json() for batch in batches)

    async def read(self) -> FeedBatch:
        return FeedBatch.model_validate_json(next(self._batches, '{"articles":[]}'))
