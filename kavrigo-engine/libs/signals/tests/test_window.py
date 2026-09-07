"""Point-in-time window construction.

These are the tests that make backtests honest. If a window can see the future, every metric
computed from it is fiction.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from kavrigo_signals import InstrumentWindow, MarketFrame

from .conftest import AS_OF, BTC, ETH, candle, quote, trade


class TestPointInTime:
    def test_events_received_after_as_of_are_excluded(self) -> None:
        window = InstrumentWindow.build(
            BTC,
            AS_OF,
            trades=[
                trade(price="100", ago=timedelta(minutes=1)),
                # Happened before as_of, but arrived after it: not knowable yet.
                trade(price="999", ago=timedelta(seconds=1), received_lag=timedelta(seconds=5)),
            ],
        )
        assert [t.price.value for t in window.trades] == [100]

    def test_knowability_is_arrival_time_not_venue_time(self) -> None:
        """Filtering on venue time would erase the venue and network latency a live system
        actually suffers, leaking the future into every decision."""
        late = trade(price="200", ago=timedelta(minutes=5), received_lag=timedelta(minutes=10))
        assert late.venue_time < AS_OF  # it happened in the past
        assert late.received_at > AS_OF  # but we had not seen it
        window = InstrumentWindow.build(BTC, AS_OF, trades=[late])
        assert window.trades == ()

    def test_an_event_arriving_exactly_at_as_of_is_included(self) -> None:
        window = InstrumentWindow.build(BTC, AS_OF, trades=[trade(price="100", ago=timedelta(0))])
        assert len(window.trades) == 1

    def test_unclosed_candles_are_excluded(self) -> None:
        """An unclosed bar's close, high and low can still change; treating it as final is
        look-ahead bias (spec 12.3)."""
        window = InstrumentWindow.build(
            BTC,
            AS_OF,
            candles=[
                candle(close="100", ago=timedelta(minutes=2), is_closed=True),
                candle(close="101", ago=timedelta(minutes=1), is_closed=False),
            ],
        )
        assert [c.close for c in window.candles] == [100]

    def test_events_are_ordered_by_arrival(self) -> None:
        """The order a live run would have observed, not the order the venue stamped."""
        window = InstrumentWindow.build(
            BTC,
            AS_OF,
            trades=[
                trade(price="103", ago=timedelta(minutes=3), received_lag=timedelta(minutes=2)),
                trade(price="101", ago=timedelta(minutes=1)),
            ],
        )
        assert [t.price.value for t in window.trades] == [103, 101]


class TestLookbacks:
    def test_trades_within_respects_the_boundary(self) -> None:
        window = InstrumentWindow.build(
            BTC,
            AS_OF,
            trades=[
                trade(price="100", ago=timedelta(minutes=20)),
                trade(price="101", ago=timedelta(minutes=10)),
                trade(price="102", ago=timedelta(minutes=1)),
            ],
        )
        assert len(window.trades_within(timedelta(minutes=15))) == 2
        assert len(window.trades_within(timedelta(minutes=5))) == 1

    def test_span_reports_how_much_history_is_present(self) -> None:
        window = InstrumentWindow.build(
            BTC, AS_OF, trades=[trade(price="100", ago=timedelta(minutes=30))]
        )
        assert window.span == timedelta(minutes=30)
        assert window.covers(timedelta(minutes=15))
        assert not window.covers(timedelta(hours=1))

    def test_an_empty_window_covers_nothing(self) -> None:
        window = InstrumentWindow.build(BTC, AS_OF)
        assert window.span == timedelta(0)
        assert not window.covers(timedelta(seconds=1))
        assert window.latest_trade is None
        assert window.latest_quote is None


class TestMarketFrame:
    def test_windows_must_share_one_as_of(self) -> None:
        """Comparing an asset priced at 12:00 against a benchmark priced at 12:05 would
        manufacture outperformance out of a timing difference."""
        btc = InstrumentWindow.build(BTC, AS_OF)
        eth = InstrumentWindow.build(ETH, AS_OF + timedelta(minutes=5))
        with pytest.raises(ValueError, match="mixing decision times"):
            MarketFrame.of(AS_OF, [btc, eth])

    def test_windows_are_addressable_by_instrument_or_key(self) -> None:
        frame = MarketFrame.of(
            AS_OF, [InstrumentWindow.build(BTC, AS_OF), InstrumentWindow.build(ETH, AS_OF)]
        )
        assert frame.window_for(BTC) is not None
        assert frame.window_for("ETH-USDT.BINANCE") is not None
        assert frame.window_for("SOL-USDT.BINANCE") is None
        assert len(frame.instruments) == 2

    def test_a_quote_only_window_still_builds(self) -> None:
        window = InstrumentWindow.build(BTC, AS_OF, quotes=[quote(bid="100", ask="101")])
        assert window.latest_quote is not None
        assert window.latest_trade is None


class TestDeterministicOrdering:
    """Sorting on the timestamp alone is a partial order, and a partial order is not enough.

    Python's sort is stable, so events sharing a millisecond keep their input order. Ingestion
    delivers out of order, so without a content tiebreak a replay would pick a different
    "latest" event and disagree with the original run.
    """

    def _simultaneous(self) -> list[object]:
        moment = timedelta(minutes=1)
        return [
            trade(price="100", quantity="1", ago=moment),
            trade(price="200", quantity="2", ago=moment),
            trade(price="300", quantity="3", ago=moment),
        ]

    def test_simultaneous_events_sort_identically_whatever_the_input_order(self) -> None:
        events = self._simultaneous()
        forward = InstrumentWindow.build(BTC, AS_OF, trades=events)  # type: ignore[arg-type]
        backward = InstrumentWindow.build(BTC, AS_OF, trades=list(reversed(events)))  # type: ignore[arg-type]
        assert [t.price.value for t in forward.trades] == [t.price.value for t in backward.trades]

    def test_the_latest_event_is_stable_under_reordering(self) -> None:
        events = self._simultaneous()
        forward = InstrumentWindow.build(BTC, AS_OF, trades=events)  # type: ignore[arg-type]
        backward = InstrumentWindow.build(BTC, AS_OF, trades=list(reversed(events)))  # type: ignore[arg-type]
        assert forward.latest_trade is not None
        assert backward.latest_trade is not None
        assert forward.latest_trade.price.value == backward.latest_trade.price.value

    def test_a_venue_sequence_wins_the_tiebreak(self) -> None:
        """Where the venue supplies an ordering, it is the venue's, not ours."""
        moment = timedelta(minutes=1)
        first = trade(price="500", ago=moment).model_copy(update={"sequence": 1})
        second = trade(price="100", ago=moment).model_copy(update={"sequence": 2})
        window = InstrumentWindow.build(BTC, AS_OF, trades=[second, first])
        assert [t.sequence for t in window.trades] == [1, 2]
