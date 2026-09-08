"""Text-only extraction, never an HTML renderer or a complete injection detector.

Official stdlib behavior verified 2026-09-08:
https://docs.python.org/3.13/library/html.parser.html (no automatic matching of closing tags)
https://docs.python.org/3.13/library/unicodedata.html (NFKC/category)
https://docs.python.org/3.13/library/urllib.parse.html (parsing is not security validation)
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import unicodedata
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

from kavrigo_news.contracts import Entity, SourcePolicy

_HIDDEN = frozenset({"script", "style", "iframe", "template", "noscript", "svg", "math", "object"})
_SIGNALS = {
    "instruction_override": r"(?:ignore|disregard|override).{0,60}(?:instructions?|system|risk|policy|limits?)",
    "role_spoof": r"(?:<\|(?:system|assistant|im_start)\|>|\[(?:system|inst)\]|(?:system|developer)\s*:)",
    "secret_request": r"(?:reveal|send|print|exfiltrate|show).{0,60}(?:secret|password|private.key|api.key|system.prompt)",
    "execution_request": r"(?:execute|run).{0,30}(?:shell|command|subprocess|curl|python)|(?:disable|bypass).{0,30}(?:risk|safety|validation)",
}


class QuarantineError(ValueError):
    def __init__(self, *codes: str) -> None:
        self.codes = codes
        super().__init__(",".join(codes))


def digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize(text: str) -> str:
    # Remove format/control characters so zero-width inserted instructions cannot hide from
    # the simple detectors. Surrogates are invalid input, not silently repaired Unicode.
    text = unicodedata.normalize("NFKC", text)
    if any(unicodedata.category(char) == "Cs" for char in text):
        raise QuarantineError("invalid_unicode")
    text = "".join(
        char if not unicodedata.category(char).startswith("C") else " " if char.isspace() else ""
        for char in text
    )
    return " ".join(text.split())


def injection_signals(text: str) -> tuple[str, ...]:
    normalized = normalize(unescape(text)).casefold()
    return tuple(code for code, pattern in _SIGNALS.items() if re.search(pattern, normalized))


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _HIDDEN:
            self.hidden.append(tag)
        if not self.hidden:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        # Mismatched hidden markup must not expose its remaining contents.
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        if not self.hidden:
            self.parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self.hidden:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def sanitize(title: str, body_html: str) -> str:
    raw = title + "\n" + body_html
    # Validate Unicode before encoding; cap bytes as well as code points.
    normalize(raw)
    if len(raw.encode("utf-8")) > 131_072:
        raise QuarantineError("content_size")
    signals = injection_signals(raw)
    if signals:
        raise QuarantineError(*signals)
    parser = _TextParser()
    parser.feed(raw)
    parser.close()
    if parser.hidden:
        raise QuarantineError("malformed_hidden_markup")
    text = normalize("".join(parser.parts))
    if not text or len(text) > 32_768:
        raise QuarantineError("content_size")
    # Scan both raw and visible text: split tags can hide instructions from the first pass.
    signals = injection_signals(text)
    if signals:
        raise QuarantineError(*signals)
    return text


def canonical_url(url: str, source: SourcePolicy) -> str:
    if any(char.isspace() or ord(char) < 32 for char in url) or "\\" in url:
        raise QuarantineError("source_url")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        if (
            parts.scheme not in {"https", "http"}
            or not host
            or host not in source.allowed_hosts
            or parts.username is not None
            or parts.password is not None
            or parts.port not in {None, 80 if parts.scheme == "http" else 443}
            or host == "localhost"
            or host.endswith((".localhost", ".local"))
        ):
            raise QuarantineError("source_url")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise QuarantineError("source_url")
    except ValueError:
        raise QuarantineError("source_url") from None
    # Preserve query semantics (including order). A fragment has no source-document identity.
    # Nothing resolves DNS, follows redirects, fetches links or trusts claimed primary URLs.
    return urlunsplit((parts.scheme, host, parts.path or "/", parts.query, ""))


class EntityMapper:
    def __init__(self, entities: tuple[Entity, ...]) -> None:
        self.entities = tuple(
            Entity.model_validate_json(item.model_dump_json()) for item in entities
        )
        if len(self.entities) > 64 or len({e.entity_id for e in self.entities}) != len(
            self.entities
        ):
            raise ValueError("entity registry must contain at most 64 distinct entities")
        aliases = [normalize(a).casefold() for e in self.entities for a in e.aliases]
        if len(set(aliases)) != len(aliases):
            raise ValueError("ambiguous entity aliases")

    def match(self, text: str) -> tuple[Entity, ...]:
        normalized = normalize(text).casefold()
        return tuple(
            entity
            for entity in self.entities
            if any(
                re.search(
                    r"(?<!\w)" + re.escape(normalize(alias).casefold()) + r"(?!\w)", normalized
                )
                for alias in entity.aliases
            )
        )
