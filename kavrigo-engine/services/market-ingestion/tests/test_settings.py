"""Provider selection must fail closed when product-use rights are unsuitable or unconfirmed."""

from kavrigo_market_ingestion.settings import default_venues


def test_default_feed_is_binance_market_data_only_and_development_only() -> None:
    venues = default_venues()

    assert len(venues) == 1
    venue = venues[0]
    assert venue.venue == "BINANCE"
    assert venue.url == "wss://data-stream.binance.vision/ws"
    assert venue.license_ref is None
    assert {instrument.value for instrument in venue.instruments.instruments} == {
        "BTC-USDT.BINANCE",
        "ETH-USDT.BINANCE",
    }
