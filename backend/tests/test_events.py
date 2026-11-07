import asyncio
from pathlib import Path

import httpx
import pytest

from gleanery.app import create_app
from gleanery.deps import AppDeps
from gleanery.events import EventBus
from tests.support.memory import MemoryCredentialStore, no_model


async def test_broadcast_slow_subscriber_and_close() -> None:
    bus = EventBus()
    slow, fast = bus.subscribe(), bus.subscribe()
    slow_first = asyncio.ensure_future(anext(slow))
    fast_first = asyncio.ensure_future(anext(fast))
    await asyncio.sleep(0)
    bus.publish("app_state.changed")
    assert (await slow_first).id == (await fast_first).id == 1
    for _ in range(257):
        bus.publish("app_state.changed")
        assert (await anext(fast)).type == "app_state.changed"
    with pytest.raises(StopAsyncIteration):
        await anext(slow)
    waiting = asyncio.ensure_future(anext(fast))
    await asyncio.sleep(0)
    bus.close()
    with pytest.raises(StopAsyncIteration):
        await waiting
    with pytest.raises(StopAsyncIteration):
        await anext(bus.subscribe())


async def test_sse_and_auth(tmp_path: Path) -> None:
    class Clock:
        bus: EventBus
        calls = 0

        def now_ms(self) -> int:
            return 0

        async def sleep(self, seconds: float) -> None:
            assert seconds == 15
            self.calls += 1
            if self.calls == 1:
                return
            await asyncio.sleep(0)
            self.bus.publish("conversation.updated", {"conversation_id": 42})
            await asyncio.sleep(0.01)
            self.bus.close()

    clock = Clock()
    app = create_app(
        AppDeps(
            data_dir=tmp_path,
            launch_token="secret",
            port=8765,
            clock=clock,
            model_resolver=no_model,
            credential_store=MemoryCredentialStore(),
        )
    )
    clock.bus = app.state.events
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765"
    ) as client:
        assert (await client.get("/api/events")).status_code == 401
        client.cookies.set("gleanery_session", "secret")
        async with client.stream("GET", "/api/events") as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            body = (await response.aread()).decode()
            assert ": ping\n\n" in body
            assert 'event: conversation.updated\ndata: {"conversation_id": 42}\nid: 1\n\n' in body
    assert not clock.bus._subscribers


async def test_disconnect_cleans_subscription(tmp_path: Path) -> None:
    from starlette.types import Message, Receive, Scope, Send

    class Clock:
        bus: EventBus

        def now_ms(self) -> int:
            return 0

        async def sleep(self, seconds: float) -> None:
            self.bus.publish("app_state.changed")
            await asyncio.Event().wait()

    clock = Clock()
    app = create_app(
        AppDeps(
            data_dir=tmp_path,
            launch_token="secret",
            port=8765,
            clock=clock,
            model_resolver=no_model,
            credential_store=MemoryCredentialStore(),
        )
    )
    clock.bus = app.state.events
    disconnected = asyncio.Event()
    first_request = True

    async def receive() -> Message:
        nonlocal first_request
        if first_request:
            first_request = False
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body" and b"event:" in message.get("body", b""):
            disconnected.set()

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/events",
        "raw_path": b"/api/events",
        "query_string": b"",
        "headers": [(b"host", b"127.0.0.1:8765"), (b"cookie", b"gleanery_session=secret")],
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 8765),
    }
    receiver: Receive = receive
    sender: Send = send
    await asyncio.wait_for(app(scope, receiver, sender), timeout=2)
    assert disconnected.is_set()
    assert not clock.bus._subscribers
