"""End-to-end local socket → parser → health → disposable count."""

import json

from websockets.asyncio.server import ServerConnection, serve

from kavrigo_domain import InstrumentId
from kavrigo_market_ingestion import CountingSink, IngestionPipeline, PipelineConfig
from kavrigo_marketdata import (
    BinanceSpotParser,
    Channel,
    InstrumentMap,
    PublicWebSocketTransport,
    StreamKey,
)


async def test_public_socket_reconnects_and_deduplicates() -> None:
    connection_count = 0
    subscriptions: list[dict[str, object]] = []

    async def handler(connection: ServerConnection) -> None:
        nonlocal connection_count
        connection_count += 1
        subscriptions.append(json.loads(await connection.recv()))
        trade_id = connection_count
        trade = {
            "e": "trade",
            "E": 1772366400000 + trade_id,
            "s": "BTCUSDT",
            "t": trade_id,
            "p": "61250.10000000",
            "q": "0.01000000",
            "T": 1772366400000 + trade_id,
            "m": False,
            "M": True,
        }
        await connection.send(json.dumps(trade))
        await connection.send(json.dumps(trade))

    instrument = InstrumentId.parse("BTC-USDT.BINANCE")
    async with serve(handler, "127.0.0.1", 0, ping_interval=None) as server:
        assert server.sockets is not None
        port = server.sockets[0].getsockname()[1]
        sink = CountingSink()
        pipeline = IngestionPipeline(
            parser=BinanceSpotParser(),
            transport=PublicWebSocketTransport(
                f"ws://127.0.0.1:{port}", allow_insecure_loopback=True
            ),
            instruments=InstrumentMap({"BTCUSDT": instrument}),
            channels=(Channel.TRADES,),
            sinks=[sink],
            config=PipelineConfig(max_reconnects=1),
        )
        try:
            stats = await pipeline.run()
        finally:
            await pipeline.aclose()

    assert connection_count == 2
    assert (
        subscriptions
        == [
            {"method": "SUBSCRIBE", "params": ["btcusdt@trade"], "id": 1},
        ]
        * 2
    )
    assert stats.events == sink.count == 2
    assert stats.dropped_duplicate_or_reordered == 2
    assert (
        pipeline.monitor.health_for(StreamKey.of("BINANCE", instrument, Channel.TRADES)).reconnects
        == 2
    )
