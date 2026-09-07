"""Structured logging (``MASTER_BUILD_SPEC.md`` §26.1).

JSON logs by default so that they are queryable. Two rules matter more than format:

* **Never log a secret.** Exchange credentials, model API keys and KMS material must not reach
  application logs (``MASTER_BUILD_SPEC.md`` §15.2). The redaction processor below is a safety
  net, not a licence to pass secrets into log calls.
* **Always carry request and workspace context** so a log line can be tied to a tenant and a
  trace without a join.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.typing import EventDict, WrappedLogger

__all__ = ["configure_logging", "get_logger"]

_REDACT_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "password",
        "token",
        "authorization",
        "credential",
        "private_key",
        "mnemonic",
        "seed_phrase",
        "clerk_secret_key",
        "exchange_api_key",
        "exchange_api_secret",
    }
)


def _redact(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    """Replace anything that looks like a credential before it is emitted."""
    for key in list(event_dict):
        if key.lower() in _REDACT_KEYS:
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=getattr(logging, level))

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=True)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
