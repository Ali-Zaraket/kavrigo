"""WebSocket transport, separated from parsing.

Splitting the socket from the parser is what makes venue adapters testable without a network:
every parser test runs against recorded frames, and every reconnect/gap test runs against a
scripted fake. ``MASTER_BUILD_SPEC.md`` §37 requires replay tests for reconnect, out-of-order,
duplicate and sequence-gap scenarios — none of which can be provoked reliably against a live
venue.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol, runtime_checkable

__all__ = ["ScriptedTransport", "Transport", "TransportClosed", "backoff_delays"]


class TransportClosed(Exception):
    """The connection ended. Expected during normal operation, not an error in itself."""


@runtime_checkable
class Transport(Protocol):
    """A duplex frame channel. One connection attempt per ``connect``."""

    async def connect(self) -> None: ...
    async def send(self, payload: dict[str, Any]) -> None: ...
    def frames(self) -> AsyncIterator[dict[str, Any]]: ...
    async def close(self) -> None: ...


def backoff_delays(
    *,
    base_seconds: float = 0.5,
    factor: float = 2.0,
    max_seconds: float = 30.0,
    jitter: float = 0.25,
    rng: random.Random | None = None,
) -> AsyncIterator[float]:
    """Exponential backoff with jitter, for reconnect loops.

    Jitter is not decoration: without it, every consumer that lost a shared venue connection
    retries on the same schedule and hammers the venue in lockstep the moment it recovers.
    """

    async def _generate() -> AsyncIterator[float]:
        source = rng or random.Random()  # noqa: S311 - jitter, not cryptography
        delay = base_seconds
        while True:
            spread = delay * jitter
            yield max(0.0, delay + source.uniform(-spread, spread))
            delay = min(max_seconds, delay * factor)

    return _generate()


class ScriptedTransport:
    """A transport that replays a fixed script of frames, for tests.

    Supports the failure shapes that matter: a mid-stream disconnect, a reconnect that resumes
    from a different sequence, and malformed frames.
    """

    def __init__(
        self,
        sessions: Sequence[Sequence[dict[str, Any] | str | Exception]],
        *,
        frame_delay: float = 0.0,
    ) -> None:
        self._sessions = [list(session) for session in sessions]
        self._frame_delay = frame_delay
        self._session_index = -1
        self._sent: list[dict[str, Any]] = []
        self._closed = False

    @property
    def sent(self) -> list[dict[str, Any]]:
        """Payloads the caller sent — used to assert the subscribe frame is correct."""
        return list(self._sent)

    @property
    def connect_count(self) -> int:
        return self._session_index + 1

    async def connect(self) -> None:
        self._session_index += 1
        self._closed = False
        if self._session_index >= len(self._sessions):
            raise TransportClosed("no further scripted sessions")

    async def send(self, payload: dict[str, Any]) -> None:
        if self._closed:
            raise TransportClosed("send on a closed transport")
        self._sent.append(payload)

    async def frames(self) -> AsyncIterator[dict[str, Any]]:
        for item in self._sessions[self._session_index]:
            if self._closed:
                return
            if isinstance(item, Exception):
                raise item
            if self._frame_delay:
                await asyncio.sleep(self._frame_delay)
            yield json.loads(item) if isinstance(item, str) else item
        raise TransportClosed("scripted session exhausted")

    async def close(self) -> None:
        self._closed = True


@contextlib.asynccontextmanager
async def closing(transport: Transport) -> AsyncIterator[Transport]:
    try:
        yield transport
    finally:
        await transport.close()
