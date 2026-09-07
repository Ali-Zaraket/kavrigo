"""Instrument identity: a ticker is not an instrument."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kavrigo_domain import IdPrefix, InstrumentClass, InstrumentId, new_id


class TestInstrumentId:
    @pytest.mark.parametrize(
        "value",
        ["BTC-USDT.BINANCE", "ETH-USD.COINBASE", "SOL-USDT.BINANCE:perpetual"],
    )
    def test_canonical_round_trip(self, value: str) -> None:
        assert InstrumentId.parse(value).value == value

    def test_spot_omits_the_class_suffix(self) -> None:
        instrument = InstrumentId(base="BTC", quote="USDT", venue="BINANCE")
        assert instrument.instrument_class is InstrumentClass.SPOT
        assert instrument.value == "BTC-USDT.BINANCE"

    @pytest.mark.parametrize(
        "value",
        ["BTC", "BTC-USDT", "btc-usdt.binance", "BTC-USDT.BINANCE:futures", "BTC/USDT.BINANCE"],
    )
    def test_ambiguous_identifiers_are_rejected(self, value: str) -> None:
        with pytest.raises(ValueError, match="invalid instrument id"):
            InstrumentId.parse(value)

    def test_base_and_quote_must_differ(self) -> None:
        with pytest.raises(ValidationError, match="must differ"):
            InstrumentId(base="BTC", quote="BTC", venue="BINANCE")

    def test_only_spot_is_executable_in_v1(self) -> None:
        assert InstrumentClass.SPOT.is_executable_in_v1
        assert not InstrumentClass.PERPETUAL.is_executable_in_v1


class TestEntityIds:
    def test_generated_ids_are_prefixed_and_unique(self) -> None:
        first = new_id(IdPrefix.DECISION)
        second = new_id(IdPrefix.DECISION)
        assert first.startswith("dec_")
        assert first != second
        assert len(first) == len("dec_") + 32
