"""Structured API errors (``MASTER_BUILD_SPEC.md`` §49, ``AGENTS.md`` § API principles).

Clients get a stable machine-readable ``code``, never a raw exception string. Leaking internal
detail into an error body is both an information-disclosure risk and an unstable contract.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

__all__ = ["ApiError", "ErrorBody", "ErrorCode", "install_exception_handlers"]


class ErrorCode(StrEnum):
    """Stable error codes. Add, never repurpose."""

    VALIDATION_FAILED = "validation_failed"
    NOT_FOUND = "not_found"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    WORKSPACE_REQUIRED = "workspace_required"
    CONFLICT = "conflict"
    IDEMPOTENCY_KEY_REUSED = "idempotency_key_reused"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    LIVE_TRADING_DISABLED = "live_trading_disabled"
    INTERNAL_ERROR = "internal_error"


class ErrorBody(BaseModel):
    """The response body for every error."""

    code: ErrorCode
    message: str
    request_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ApiError(Exception):
    """Raise this rather than ``HTTPException`` so every error has a stable code."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        http_status: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}


def _api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render an :class:`ApiError` as a structured body with a stable code."""
    assert isinstance(exc, ApiError)  # registered only for ApiError
    body = ErrorBody(
        code=exc.code,
        message=exc.message,
        request_id=getattr(request.state, "request_id", None),
        details=exc.details,
    )
    return JSONResponse(status_code=exc.http_status, content=body.model_dump(mode="json"))


def _unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log the detail; return none of it.

    An unexpected exception message can carry internal structure or fragments of a payload, so
    the response says only that something failed and gives the request id to correlate with.
    """
    from kavrigo_api.logging import get_logger

    get_logger(__name__).exception(
        "unhandled_exception",
        path=request.url.path,
        request_id=getattr(request.state, "request_id", None),
        error_type=type(exc).__name__,
    )
    body = ErrorBody(
        code=ErrorCode.INTERNAL_ERROR,
        message="An unexpected error occurred.",
        request_id=getattr(request.state, "request_id", None),
    )
    return JSONResponse(status_code=500, content=body.model_dump(mode="json"))


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(Exception, _unexpected_error_handler)
