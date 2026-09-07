"""Identifier types.

``MASTER_BUILD_SPEC.md`` §49: *explicit asset/instrument IDs, not ambiguous ticker strings.*
"BTC" is not an instrument: it does not say which venue, which quote currency, or whether the
contract is spot or a perpetual. Conflating them is how a backtest silently prices one venue's
spot market with another venue's perpetual.

Entity identifiers are prefixed (``dec_``, ``ag_``, ``ord_``) so that a mis-wired identifier
fails loudly at the boundary instead of being looked up in the wrong table.
"""

from __future__ import annotations

import re
import uuid
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Self

from pydantic import Field, model_validator

from kavrigo_domain.base import DomainModel

__all__ = [
    "AgentId",
    "AgentVersionId",
    "DecisionId",
    "EvidenceId",
    "FillId",
    "IdPrefix",
    "InstrumentClass",
    "InstrumentId",
    "OrderId",
    "OrderIntentId",
    "RiskPolicyId",
    "SnapshotId",
    "VenueId",
    "WorkspaceId",
    "new_id",
]

_ASSET = r"[A-Z0-9]{2,16}"
_VENUE = r"[A-Z0-9_]{2,32}"


class InstrumentClass(StrEnum):
    """What kind of contract an instrument is.

    Only ``SPOT`` is executable in V1 (ADR 0002). Derivatives appear here because their *data*
    is a first-class signal source (``MASTER_BUILD_SPEC.md`` §7.3) even though the platform does
    not trade them.
    """

    SPOT = "spot"
    PERPETUAL = "perpetual"
    FUTURE = "future"
    OPTION = "option"
    INDEX = "index"

    @property
    def is_executable_in_v1(self) -> bool:
        return self is InstrumentClass.SPOT


VenueId = Annotated[
    str,
    Field(
        min_length=2,
        max_length=32,
        pattern=rf"^{_VENUE}$",
        description="Uppercase venue or data-source identifier, e.g. BINANCE, COINBASE, SIM.",
    ),
]


class InstrumentId(DomainModel):
    """A tradable or observable instrument, unambiguous across venues and contract types.

    Canonical string form is ``BASE-QUOTE.VENUE`` for spot, and ``BASE-QUOTE.VENUE:CLASS`` for
    everything else — for example ``BTC-USDT.BINANCE`` and ``BTC-USDT.BINANCE:perpetual``.
    """

    base: Annotated[str, Field(pattern=rf"^{_ASSET}$")]
    quote: Annotated[str, Field(pattern=rf"^{_ASSET}$")]
    venue: VenueId
    instrument_class: InstrumentClass = InstrumentClass.SPOT

    _CANONICAL: ClassVar[re.Pattern[str]] = re.compile(
        rf"^(?P<base>{_ASSET})-(?P<quote>{_ASSET})\.(?P<venue>{_VENUE})(?::(?P<cls>[a-z]+))?$"
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.base == self.quote:
            raise ValueError("base and quote assets must differ")
        return self

    @property
    def value(self) -> str:
        """Canonical string form, stable enough to use as a partition or cache key."""
        suffix = (
            ""
            if self.instrument_class is InstrumentClass.SPOT
            else f":{self.instrument_class.value}"
        )
        return f"{self.base}-{self.quote}.{self.venue}{suffix}"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def parse(cls, value: str) -> Self:
        """Parse the canonical string form. Raises on anything ambiguous."""
        match = cls._CANONICAL.match(value.strip())
        if match is None:
            raise ValueError(
                f"invalid instrument id {value!r}; expected BASE-QUOTE.VENUE[:class], "
                "e.g. BTC-USDT.BINANCE"
            )
        raw_class = match.group("cls")
        try:
            instrument_class = InstrumentClass(raw_class) if raw_class else InstrumentClass.SPOT
        except ValueError as exc:
            known = ", ".join(c.value for c in InstrumentClass)
            raise ValueError(
                f"invalid instrument id {value!r}: unknown instrument class {raw_class!r} "
                f"(known: {known})"
            ) from exc
        return cls(
            base=match.group("base"),
            quote=match.group("quote"),
            venue=match.group("venue"),
            instrument_class=instrument_class,
        )


class IdPrefix(StrEnum):
    """Prefixes for entity identifiers."""

    WORKSPACE = "ws"
    AGENT = "ag"
    AGENT_VERSION = "av"
    PROMPT_VERSION = "pv"
    RISK_POLICY = "rp"
    EXECUTION_POLICY = "ep"
    SNAPSHOT = "snap"
    EVIDENCE = "ev"
    DECISION = "dec"
    MODEL_CALL = "mc"
    ORDER_INTENT = "oi"
    RISK_EVALUATION = "re"
    ORDER = "ord"
    FILL = "fill"
    RUN = "run"
    EVENT = "evt"


def new_id(prefix: IdPrefix) -> str:
    """Generate a prefixed identifier, e.g. ``dec_9f2c...``.

    UUID4 keeps identifiers unguessable, which matters because identifiers appear in shareable
    evidence and performance pages.
    """
    return f"{prefix.value}_{uuid.uuid4().hex}"


def _prefixed(prefix: IdPrefix) -> Any:
    return Field(pattern=rf"^{prefix.value}_[0-9a-f]{{32}}$", description=f"{prefix.value}_ id")


WorkspaceId = Annotated[str, _prefixed(IdPrefix.WORKSPACE)]
AgentId = Annotated[str, _prefixed(IdPrefix.AGENT)]
AgentVersionId = Annotated[str, _prefixed(IdPrefix.AGENT_VERSION)]
RiskPolicyId = Annotated[str, _prefixed(IdPrefix.RISK_POLICY)]
SnapshotId = Annotated[str, _prefixed(IdPrefix.SNAPSHOT)]
EvidenceId = Annotated[str, _prefixed(IdPrefix.EVIDENCE)]
DecisionId = Annotated[str, _prefixed(IdPrefix.DECISION)]
OrderIntentId = Annotated[str, _prefixed(IdPrefix.ORDER_INTENT)]
OrderId = Annotated[str, _prefixed(IdPrefix.ORDER)]
FillId = Annotated[str, _prefixed(IdPrefix.FILL)]
