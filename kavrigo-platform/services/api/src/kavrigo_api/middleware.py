"""Request context middleware.

Every request gets an id that appears in logs and in error bodies, so a user-reported failure
can be found without guessing. Workspace context is *read* here but never trusted for
authorization — the tenant boundary is enforced in the backend and by PostgreSQL RLS
(``MASTER_BUILD_SPEC.md`` §20), and a header alone will never grant access.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

__all__ = ["RequestContextMiddleware"]

_REQUEST_ID_HEADER = "x-request-id"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id, bind logging context, and record request latency."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(_REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - started) * 1000)

        response.headers[_REQUEST_ID_HEADER] = request_id
        structlog.get_logger(__name__).info(
            "http_request",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
