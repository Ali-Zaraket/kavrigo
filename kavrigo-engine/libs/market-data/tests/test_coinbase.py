"""Coinbase Exchange adapter.

Frames follow the layout documented at
https://docs.cdp.coinbase.com/exchange/websocket-feed/channels (verified 2026-09-07).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kavrigo_domain import AggressorSide, BookTicker, MarketTrade
from kavrigo_marketdata import Channel, CoinbaseExchangeParser, InstrumentMap

from .conftest import RECEIVED_AT


@pytest.fixture
def parser() -> CoinbaseExchangeParser:
    return CoinbaseExchangeParser()


def _match(**overrides: object) -> dict[str, object]:
    frame = {
        "type": "match",
        "trade_id": 552001,
        "sequence": 40100,
        "maker_order_id": "1b1c1d1e-0000-4000-8000-000000000001",
        "taker_order_id": "1b1c1d1e-0000-4000-8000-000000000002",
        "time": "2026-03-01T12:00:00.100000Z",
        "product_id": "BTC-USD",
        "size": "0.02100000",
        "price": "61251.02",
        "side": "sell",
    }
    frame.update(overrides)
    return frame


class TestMatchParsing:
    def test_a_match_is_normalized(
        self, parser: CoinbaseExchangeParser, coinbase_instruments: InstrumentMap
    ) -> None:
        parsed = parser.parse(_match(), received_at=RECEIVED_AT, instruments=coinbase_instruments)
        trade = parsed.event
        assert isinstance(trade, MarketTrade)
        assert trade.instrument_id.value == "BTC-USD.COINBASE"
        assert trade.price.value == Decimal("61251.02")
        assert trade.quantity.value == Decimal("0.02100000")
        assert trade.venue_time == datetime(2026, 3, 1, 12, 0, 0, 100000, tzinfo=UTC)
        assert trade.sequence == 40100

    def test_side_is_the_maker_so_the_aggressor_is_inverted(
        self, parser: CoinbaseExchangeParser, coinbase_instruments: InstrumentMap
    ) -> None:
        """Documented: "The side field indicates the maker order side."

        A maker sell means the taker bought. Passing the venue field straight through would
        invert every order-flow feature built on it.
        """
        maker_sell = parser.parse(
            _match(side="sell"), received_at=RECEIVED_AT, instruments=coinbase_instruments
        )
        assert isinstance(maker_sell.event, MarketTrade)
        assert maker_sell.event.aggressor is AggressorSide.BUY

        maker_buy = parser.parse(
            _match(side="buy"), received_at=RECEIVED_AT, instruments=coinbase_instruments
        )
        assert isinstance(maker_buy.event, MarketTrade)
        assert maker_buy.event.aggressor is AggressorSide.SELL

    def test_an_unrecognised_side_is_unknown_not_guessed(
        self, parser: CoinbaseExchangeParser, coinbase_instruments: InstrumentMap
    ) -> None:
        parsed = parser.parse(
            _match(side="both"), received_at=RECEIVED_AT, instruments=coinbase_instruments
        )
        assert isinstance(parsed.event, MarketTrade)
        assert parsed.event.aggressor is AggressorSide.UNKNOWN

    def test_last_match_is_parsed_like_a_match(
        self, parser: CoinbaseExchangeParser, coinbase_instruments: InstrumentMap
    ) -> None:
        """`last_match` is the snapshot sent on subscribe; the payload shape is the same."""
        parsed = parser.parse(
            _match(type="last_match"),
            received_at=RECEIVED_AT,
            instruments=coinbase_instruments,
        )
        assert isinstance(parsed.event, MarketTrade)

    def test_a_naive_timestamp_is_refused(
        self, parser: CoinbaseExchangeParser, coinbase_instruments: InstrumentMap
    ) -> None:
        """Without an offset the timestamp is ambiguous, and freshness becomes a guess."""
        parsed = parser.parse(
            _match(time="2026-03-01T12:00:00.100000"),
            received_at=RECEIVED_AT,
            instruments=coinbase_instruments,
        )
        assert parsed.event is None


class TestTickerParsing:
    def test_best_bid_and_ask_are_normalized(
        self, parser: CoinbaseExchangeParser, coinbase_instruments: InstrumentMap
    ) -> None:
        parsed = parser.parse(
            {
                "type": "ticker",
                "sequence": 40102,
                "product_id": "BTC-USD",
                "price": "61250.55",
                "best_bid": "61250.10",
                "best_bid_size": "0.94210000",
                "best_ask": "61250.90",
                "best_ask_size": "1.20410000",
                "side": "buy",
                "time": "2026-03-01T12:00:00.280000Z",
                "trade_id": 552002,
                "last_size": "0.00450000",
            },
            received_at=RECEIVED_AT,
            instruments=coinbase_instruments,
        )
        ticker = parsed.event
        assert isinstance(ticker, BookTicker)
        assert ticker.spread == Decimal("0.80")
        assert ticker.mid_price == Decimal("61250.50")
        assert ticker.venue_time is not None


class TestControlFrames:
    @pytest.mark.parametrize(
        "frame_type", ["subscriptions", "heartbeat", "status", "error", "received", "open", "done"]
    )
    def test_protocol_frames_are_control(
        self,
        parser: CoinbaseExchangeParser,
        coinbase_instruments: InstrumentMap,
        frame_type: str,
    ) -> None:
        parsed = parser.parse(
            {"type": frame_type, "sequence": 7},
            received_at=RECEIVED_AT,
            instruments=coinbase_instruments,
        )
        assert parsed.is_control
        assert parsed.sequence == 7

    def test_an_unknown_product_is_dropped(
        self, parser: CoinbaseExchangeParser, coinbase_instruments: InstrumentMap
    ) -> None:
        parsed = parser.parse(
            _match(product_id="SOL-USD"),
            received_at=RECEIVED_AT,
            instruments=coinbase_instruments,
        )
        assert parsed.is_skipped

    @pytest.mark.parametrize(
        "frame",
        [
            {},
            {"type": "match"},
            {
                "type": "match",
                "product_id": "BTC-USD",
                "price": "x",
                "size": "1",
                "time": "2026-03-01T12:00:00Z",
            },
            {"type": "ticker", "product_id": "BTC-USD"},
            {"type": "brand_new_channel", "product_id": "BTC-USD"},
        ],
    )
    def test_malformed_frames_never_raise(
        self,
        parser: CoinbaseExchangeParser,
        coinbase_instruments: InstrumentMap,
        frame: dict[str, object],
    ) -> None:
        assert (
            parser.parse(frame, received_at=RECEIVED_AT, instruments=coinbase_instruments).event
            is None
        )


class TestSubscription:
    def test_the_subscribe_payload_requests_heartbeat_for_gap_detection(
        self, parser: CoinbaseExchangeParser, coinbase_instruments: InstrumentMap
    ) -> None:
        payload = parser.subscribe_payloads(
            coinbase_instruments, (Channel.TRADES, Channel.BOOK_TICKER)
        )[0]
        assert payload["type"] == "subscribe"
        assert payload["product_ids"] == ["BTC-USD"]
        assert set(payload["channels"]) == {"matches", "ticker", "heartbeat"}
