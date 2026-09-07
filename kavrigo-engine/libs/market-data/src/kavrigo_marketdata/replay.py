"""Replay recorded venue frames.

Recorded frames are how ingestion is tested and how a historical run is reproduced. The file
format is JSON Lines, one raw venue frame per line, exactly as it came off the socket:

```json
{"received_at": "2026-03-01T12:00:00.123Z", "frame": {"e": "trade", ...}}
```

``received_at`` is recorded alongside the frame because the venue timestamp alone cannot answer
"when did we know this?", and point-in-time correctness depends on that distinction
(``MASTER_BUILD_SPEC.md`` §8.5).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kavrigo_marketdata.adapter import InstrumentMap, MarketEvent, ParsedFrame, VenueParser

__all__ = ["RecordedFrame", "iter_recorded_frames", "replay_events", "write_recording"]


class RecordedFrame:
    __slots__ = ("frame", "received_at")

    def __init__(self, received_at: datetime, frame: dict[str, Any]) -> None:
        self.received_at = received_at
        self.frame = frame


def iter_recorded_frames(path: Path) -> Iterator[RecordedFrame]:
    """Read a JSONL recording. Blank lines are skipped; malformed lines raise.

    A malformed recording is a broken fixture, not untrusted input, so failing loudly is right —
    silently skipping would let a test pass against half a file.
    """
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
                received_at = datetime.fromisoformat(record["received_at"])
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                raise ValueError(f"{path}:{number}: malformed recording line") from exc
            if received_at.tzinfo is None:
                raise ValueError(f"{path}:{number}: received_at must carry a UTC offset")
            yield RecordedFrame(received_at.astimezone(UTC), record["frame"])


def replay_events(
    path: Path, parser: VenueParser, instruments: InstrumentMap
) -> Iterator[tuple[RecordedFrame, ParsedFrame]]:
    """Parse a recording, yielding each frame with its result — including skips.

    Skips are yielded rather than filtered so a replay test can assert *why* a frame produced no
    event, which is how a silently-changed venue format gets noticed.
    """
    for recorded in iter_recorded_frames(path):
        yield (
            recorded,
            parser.parse(recorded.frame, received_at=recorded.received_at, instruments=instruments),
        )


def replayed_market_events(
    path: Path, parser: VenueParser, instruments: InstrumentMap
) -> Iterator[MarketEvent]:
    for _recorded, parsed in replay_events(path, parser, instruments):
        if parsed.event is not None:
            yield parsed.event


def write_recording(path: Path, frames: Iterator[RecordedFrame]) -> int:
    """Write a JSONL recording. Returns the number of frames written."""
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for recorded in frames:
            handle.write(
                json.dumps(
                    {
                        "received_at": recorded.received_at.astimezone(UTC).isoformat(),
                        "frame": recorded.frame,
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
            count += 1
    return count
