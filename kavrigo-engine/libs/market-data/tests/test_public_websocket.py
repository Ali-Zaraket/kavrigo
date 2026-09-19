"""The real socket boundary is exercised against a local server, never an exchange."""

import json

import pytest
from websockets.asyncio.server import ServerConnection, serve

from kavrigo_marketdata import PublicWebSocketTransport, TransportClosed


def test_only_public_wss_urls_are_accepted() -> None:
    with pytest.raises(ValueError, match="public WSS"):
        PublicWebSocketTransport("ws://example.com/feed")
    with pytest.raises(ValueError, match="public WSS"):
        PublicWebSocketTransport("wss://user:secret@example.com/feed")
    with pytest.raises(ValueError, match="public WSS"):
        PublicWebSocketTransport("wss://example.com/feed?token=secret")
    with pytest.raises(ValueError, match="public WSS"):
        PublicWebSocketTransport("ws://127.0.0.1:1234/feed")
    with pytest.raises(ValueError, match="positive"):
        PublicWebSocketTransport("wss://example.com/feed", max_frame_bytes=0)


async def test_subscription_json_frames_bad_input_and_pong() -> None:
    subscriptions: list[dict[str, object]] = []

    async def handler(connection: ServerConnection) -> None:
        subscriptions.append(json.loads(await connection.recv()))
        await connection.send('{"type":"ticker","product_id":"BTC-USD"}')
        await connection.send("not-json")
        await connection.send("[]")
        await (await connection.ping(b"health"))

    async with serve(handler, "127.0.0.1", 0, ping_interval=None) as server:
        assert server.sockets is not None
        port = server.sockets[0].getsockname()[1]
        transport = PublicWebSocketTransport(f"ws://127.0.0.1:{port}", allow_insecure_loopback=True)
        await transport.connect()
        await transport.send({"type": "subscribe", "product_ids": ["BTC-USD"]})
        frames = [frame async for frame in transport.frames()]
        await transport.close()

    assert subscriptions == [{"type": "subscribe", "product_ids": ["BTC-USD"]}]
    assert frames == [
        {"type": "ticker", "product_id": "BTC-USD"},
        {"_transport_error": "invalid_json"},
        {"_transport_error": "non_object_json"},
    ]


async def test_oversized_frame_closes_bounded_connection() -> None:
    async def handler(connection: ServerConnection) -> None:
        await connection.recv()
        await connection.send(json.dumps({"data": "x" * 1024}))

    async with serve(handler, "127.0.0.1", 0, ping_interval=None) as server:
        assert server.sockets is not None
        port = server.sockets[0].getsockname()[1]
        transport = PublicWebSocketTransport(
            f"ws://127.0.0.1:{port}",
            allow_insecure_loopback=True,
            max_frame_bytes=128,
        )
        await transport.connect()
        await transport.send({"type": "subscribe"})
        with pytest.raises(TransportClosed, match="disconnected"):
            _ = [frame async for frame in transport.frames()]
        await transport.close()
