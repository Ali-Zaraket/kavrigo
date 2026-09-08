"""Fail-closed JSON boundary. No partial parsing, duplicate keys, repairs or error payload logs.

Pydantic JSON parsing permits some JSON-specific coercions and non-finite numbers; a strict
stdlib decode runs first so ExactDecimal sees (and rejects) JSON binary floats for money.
Sources verified 2026-09-08: https://docs.pydantic.dev/latest/concepts/json/ and
https://docs.python.org/3.13/library/json.html .
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import ValidationError

from kavrigo_domain import DomainModel
from kavrigo_model_gateway.contracts import FailureCode, GatewayError

# Defense in depth. This cannot identify an arbitrary unlabelled secret; the primary boundary
# is no credential-store/secret-manager dependency, narrowly registered input schemas and no
# tools or filesystem/network reads. Never log the matched content.
_SECRET_KEY = re.compile(
    r"(?:api.?key|secret|password|authorization|credential|private.?key|mnemonic|seed.?phrase|access.?token)",
    re.I,
)
_SECRET_TEXT = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+\S+|\b(?:api[_ -]?key|api[_ -]?secret|password|seed[_ -]?phrase|private[_ -]?key)\s*[:=]\s*\S+)",
    re.I,
)


def digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _screen(value: Any, depth: int = 0) -> None:
    if depth > 32:
        raise ValueError("nested input limit")
    if isinstance(value, dict):
        for key, item in value.items():
            if _SECRET_KEY.search(key):
                raise ValueError("credential-shaped field")
            _screen(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _screen(item, depth + 1)
    elif isinstance(value, str) and _SECRET_TEXT.search(value):
        raise ValueError("credential-shaped text")


def validate_json[T: DomainModel](text: str, model: type[T], *, limit: int, code: FailureCode) -> T:
    try:
        if len(text.encode("utf-8")) > limit:
            raise ValueError("byte limit")
        decoded = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
        if not isinstance(decoded, dict):
            raise ValueError("object required")
        _screen(decoded)
        return model.model_validate(decoded)
    except (ValueError, ValidationError, RecursionError, UnicodeError):
        # Deliberately drop chained exceptions: Pydantic errors contain input values.
        raise GatewayError(code) from None


def safe_system_text(text: str) -> None:
    if not text or len(text.encode("utf-8")) > 32_768 or _SECRET_TEXT.search(text):
        raise ValueError("invalid registered system text")
