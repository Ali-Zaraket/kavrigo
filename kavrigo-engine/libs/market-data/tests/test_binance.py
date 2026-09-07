"""Binance spot adapter.

Frames follow the field layout documented at
https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams (verified
2026-09-07).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kavrigo_domain import AggressorSide, BookTicker, Candle, MarketTrade
from kavrigo_marketdata import BinanceSpotParser, Channel, InstrumentMap

from .conftest import RECEIVED_AT


@pytest.fixture
def parser() -> BinanceSpotParser:
    return BinanceSpotParser()


def _trade_frame(**overrides: object) -> dict[str, object]:
    frame = {
        "e": "trade",
        "E": 1772366400000,
        "s": "BTCUSDT",
        "t": 900001,
        "p": "61250.10000000",
        "q": "0.01500000",
        "T": 1772366399950,
        "m": False,
        "M": True,
    }
    frame.update(overrides)
    return frame


class TestTradeParsing:
    def test_a_trade_is_normalized_with_exact_decimals(
        self, parser: BinanceSpotParser, binance_instruments: InstrumentMap
    ) -> None:
        parsed = parser.parse(
            _trade_frame(), received_at=RECEIVED_AT, instruments=binance_instruments
        )
        trade = parsed.event
        assert isinstance(trade, MarketTrade)
        assert trade.instrument_id.value == "BTC-USDT.BINANCE"
        assert trade.price.value == Decimal("61250.10000000")
        assert trade.quantity.value == Decimal("0.01500000")
        assert trade.venue_time == datetime(2026, 3, 1, 11, 59, 59, 950000, tzinfo=UTC)
        assert trade.received_at == RECEIVED_AT
        assert trade.venue_trade_id == "900001"

    def test_maker_buyer_means_the_seller_was_the_aggressor(
        self, parser: BinanceSpotParser, binance_instruments: InstrumentMap
    ) -> None:
        """`m` is "was the BUYER the maker?". If yes, the taker was the seller.

        Getting this backwards silently inverts CVD and every taker-imbalance feature.
        """
        parsed = parser.parse(
            _trade_frame(m=True), received_at=RECEIVED_AT, instruments=binance_instruments
        )
        assert isinstance(parsed.event, MarketTrade)
        assert parsed.event.aggressor is AggressorSide.SELL
        assert parsed.event.signed_quantity == Decimal("-0.01500000")

    def test_maker_seller_means_the_buyer_was_the_aggressor(
        self, parser: BinanceSpotParser, binance_instruments: InstrumentMap
    ) -> None:
        parsed = parser.parse(
            _trade_frame(m=False), received_at=RECEIVED_AT, instruments=binance_instruments
        )
        assert isinstance(parsed.event, MarketTrade)
        assert parsed.event.aggressor is AggressorSide.BUY
        assert parsed.event.signed_quantity == Decimal("0.01500000")

    def test_a_missing_maker_flag_is_unknown_not_guessed(
        self, parser: BinanceSpotParser, binance_instruments: InstrumentMap
    ) -> None:
        frame = _trade_frame()
        del frame["m"]
        parsed = parser.parse(frame, received_at=RECEIVED_AT, instruments=binance_instruments)
        assert isinstance(parsed.event, MarketTrade)
        assert parsed.event.aggressor is AggressorSide.UNKNOWN
        assert parsed.event.signed_quantity == 0

    def test_prices_never_pass_through_float(
        self, parser: BinanceSpotParser, binance_instruments: InstrumentMap
    ) -> None:
        """0.1 + 0.2 is exact only if the venue string was parsed as Decimal."""
        parsed = parser.parse(
            _trade_frame(p="0.10000000", q="0.20000000"),
            received_at=RECEIVED_AT,
            instruments=binance_instruments,
        )
        assert isinstance(parsed.event, MarketTrade)
        assert parsed.event.price.value + parsed.event.quantity.value == Decimal("0.3")


class TestBookTickerParsing:
    def test_best_bid_and_ask_are_normalized(
        self, parser: BinanceSpotParser, binance_instruments: InstrumentMap
    ) -> None:
        parsed = parser.parse(
            {
                "u": 400900217,
                "s": "BTCUSDT",
                "b": "61249.80000000",
                "B": "1.24500000",
                "a": "61250.20000000",
                "A": "0.87300000",
            },
            received_at=RECEIVED_AT,
            instruments=binance_instruments,
        )
        ticker = parsed.event
        assert isinstance(ticker, BookTicker)
        assert ticker.spread == Decimal("0.40000000")
        assert ticker.sequence == 400900217
        assert parsed.sequence == 400900217

    def test_book_ticker_has_no_venue_timestamp(
        self, parser: BinanceSpotParser, binance_instruments: InstrumentMap
    ) -> None:
        """The stream carries none; inventing one would understate staleness."""
        parsed = parser.parse(
            {"u": 1, "s": "BTCUSDT", "b": "1.0", "B": "1", "a": "2.0", "A": "1"},
            received_at=RECEIVED_AT,
            instruments=binance_instruments,
        )
        assert isinstance(parsed.event, BookTicker)
        assert parsed.event.venue_time is None

    def test_a_crossed_book_is_dropped_with_a_reason(
        self, parser: BinanceSpotParser, binance_instruments: InstrumentMap
    ) -> None:
        parsed = parser.parse(
            {"u": 2, "s": "BTCUSDT", "b": "3.0", "B": "1", "a": "2.0", "A": "1"},
            received_at=RECEIVED_AT,
            instruments=binance_instruments,
        )
        assert parsed.event is None
        assert parsed.reason is not None
        assert "crossed book" in parsed.reason


class TestKlineParsing:
    def _kline(self, **k: object) -> dict[str, object]:
        candle = {
            "t": 1772366400000,
            "T": 1772366459999,
            "s": "BTCUSDT",
            "i": "1m",
            "f": 900001,
            "L": 900450,
            "o": "61250.10000000",
            "c": "61262.40000000",
            "h": "61270.00000000",
            "l": "61240.10000000",
            "v": "18.42100000",
            "n": 450,
            "x": True,
            "q": "1128394.20000000",
            "V": "9.10500000",
            "Q": "557800.10000000",
            "B": "0",
        }
        candle.update(k)
        return {"e": "kline", "E": 1772366460000, "s": "BTCUSDT", "k": candle}

    def test_a_closed_candle_is_normalized(
        self, parser: BinanceSpotParser, binance_instruments: InstrumentMap
    ) -> None:
        parsed = parser.parse(
            self._kline(), received_at=RECEIVED_AT, instruments=binance_instruments
        )
        candle = parsed.event
        assert isinstance(candle, Candle)
        assert candle.is_closed
        assert candle.interval == "1m"
        assert candle.trade_count == 450
        assert candle.taker_buy_base_volume == Decimal("9.10500000")

    def test_an_unclosed_candle_is_flagged_not_dropped(
        self, parser: BinanceSpotParser, binance_instruments: InstrumentMap
    ) -> None:
        """Consumers need it for live display; a backtest must refuse it (spec 12.3)."""
        parsed = parser.parse(
            self._kline(x=False), received_at=RECEIVED_AT, instruments=binance_instruments
        )
        assert isinstance(parsed.event, Candle)
        assert parsed.event.is_closed is False

    def test_an_impossible_candle_is_rejected_by_validation(
        self, parser: BinanceSpotParser, binance_instruments: InstrumentMap
    ) -> None:
        parsed = parser.parse(
            self._kline(l="99999.0"), received_at=RECEIVED_AT, instruments=binance_instruments
        )
        assert parsed.event is None
        assert parsed.reason is not None
        assert "validation" in parsed.reason


class TestRobustness:
    def test_a_subscription_acknowledgement_is_control_not_data(
        self, parser: BinanceSpotParser, binance_instruments: InstrumentMap
    ) -> None:
        parsed = parser.parse(
            {"result": None, "id": 1}, received_at=RECEIVED_AT, instruments=binance_instruments
        )
        assert parsed.is_control
        assert parsed.event is None
        assert not parsed.is_skipped

    def test_an_unsubscribed_symbol_is_dropped(
        self, parser: BinanceSpotParser, binance_instruments: InstrumentMap
    ) -> None:
        """Symbols are mapped, never inferred: BTCUSDT cannot be split without knowing quotes."""
        parsed = parser.parse(
            _trade_frame(s="DOGEUSDT"),
            received_at=RECEIVED_AT,
            instruments=binance_instruments,
        )
        assert parsed.is_skipped
        assert parsed.reason is not None

    @pytest.mark.parametrize(
        "frame",
        [
            {},
            {"e": "trade"},
            {"e": "somethingNew", "s": "BTCUSDT"},
            {"e": "trade", "s": "BTCUSDT", "p": "not-a-number", "q": "1", "T": 1772366400000},
            {"e": "trade", "s": "BTCUSDT", "p": "-1", "q": "1", "T": 1772366400000},
            {"e": "kline", "s": "BTCUSDT", "k": "not-an-object"},
            {"data": "not-an-object"},
        ],
    )
    def test_malformed_frames_never_raise(
        self,
        parser: BinanceSpotParser,
        binance_instruments: InstrumentMap,
        frame: dict[str, object],
    ) -> None:
        """A venue adding or malforming a field must not take ingestion down."""
        parsed = parser.parse(frame, received_at=RECEIVED_AT, instruments=binance_instruments)
        assert parsed.event is None


class TestSubscription:
    def test_stream_names_are_lowercase_per_venue_convention(
        self, parser: BinanceSpotParser, binance_instruments: InstrumentMap
    ) -> None:
        names = parser.stream_names(
            binance_instruments, (Channel.TRADES, Channel.BOOK_TICKER), interval="1m"
        )
        assert "btcusdt@trade" in names
        assert "btcusdt@bookTicker" in names

    def test_candle_streams_carry_the_interval(
        self, parser: BinanceSpotParser, binance_instruments: InstrumentMap
    ) -> None:
        names = parser.stream_names(binance_instruments, (Channel.CANDLES,), interval="5m")
        assert "btcusdt@kline_5m" in names

    def test_the_subscribe_payload_matches_the_documented_shape(
        self, parser: BinanceSpotParser, binance_instruments: InstrumentMap
    ) -> None:
        payloads = parser.subscribe_payloads(binance_instruments, (Channel.TRADES,), interval="1m")
        assert payloads[0]["method"] == "SUBSCRIBE"
        assert "btcusdt@trade" in payloads[0]["params"]
