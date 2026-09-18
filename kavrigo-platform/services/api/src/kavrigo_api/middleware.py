"""Request context middleware.

Every request gets an id that appears in logs and in error bodies, so a user-reported failure
can be found without guessing. Workspace context is *read* here but never trusted for
authorization — the tenant boundary is enforced in the backend and by PostgreSQL RLS
(``MASTER_BUILD_SPEC.md`` §20), and a header alone will never grant access.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from opentelemetry import metrics, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import StatusCode, Tracer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

__all__ = ["RequestContextMiddleware"]

_REQUEST_ID_HEADER = "x-request-id"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id, bind logging context, and record request latency."""

    def __init__(
        self, app: ASGIApp, *, tracer: Tracer | None = None, meter: Meter | None = None
    ) -> None:
        super().__init__(app)
        self.tracer = tracer or trace.get_tracer("kavrigo.api")
        meter = meter or metrics.get_meter("kavrigo.api")
        self.requests = meter.create_counter("kavrigo.http.requests", unit="{request}")
        self.duration = meter.create_histogram("kavrigo.http.duration", unit="ms")

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        supplied_id = request.headers.get(_REQUEST_ID_HEADER, "")
        request_id = (
            supplied_id if re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", supplied_id) else uuid.uuid4().hex
        )
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
        )
        method = (
            request.method
            if request.method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
            else "OTHER"
        )
        started = time.perf_counter()
        status = 500
        # No raw paths, headers, bodies, baggage or automatic exception recording.
        with self.tracer.start_as_current_span(
            "control_plane.request",
            kind=trace.SpanKind.SERVER,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                response = await call_next(request)
                status = response.status_code
                response.headers[_REQUEST_ID_HEADER] = request_id
                return response
            finally:
                duration_ms = int((time.perf_counter() - started) * 1000)
                route = getattr(request.scope.get("route"), "path", "unmatched")
                labels: dict[str, str | int] = {
                    "http.request.method": method,
                    "http.route": route,
                    "http.response.status_code": status,
                }
                span.set_attributes(labels)
                if status >= 500:
                    span.set_status(StatusCode.ERROR)
                self.requests.add(1, labels)
                self.duration.record(duration_ms, labels)
                structlog.get_logger(__name__).info(
                    "http_request",
                    method=method,
                    route=route,
                    status_code=status,
                    duration_ms=duration_ms,
                )
                structlog.contextvars.clear_contextvars()
