"""全局事件 SSE。"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from fastapi.sse import EventSourceResponse, format_sse_event

from gleanery.api.deps import get_deps, get_events
from gleanery.deps import AppDeps
from gleanery.events import EventBus

router = APIRouter(prefix="/api", tags=["events"])


@router.get(
    "/events", response_class=Response, responses={200: {"content": {"text/event-stream": {}}}}
)
async def events(
    bus: Annotated[EventBus, Depends(get_events)], deps: Annotated[AppDeps, Depends(get_deps)]
) -> EventSourceResponse:
    async def stream() -> AsyncIterator[bytes]:
        subscription = bus.subscribe()
        next_event = asyncio.ensure_future(anext(subscription))
        heartbeat = asyncio.create_task(deps.clock.sleep(15))
        try:
            while True:
                done, _ = await asyncio.wait(
                    (next_event, heartbeat), return_when=asyncio.FIRST_COMPLETED
                )
                if next_event in done:
                    try:
                        event = next_event.result()
                    except StopAsyncIteration:
                        return
                    yield format_sse_event(
                        event=event.type,
                        data_str=json.dumps(event.data, ensure_ascii=False),
                        id=str(event.id),
                    )
                    next_event = asyncio.ensure_future(anext(subscription))
                if heartbeat in done:
                    heartbeat.result()
                    yield format_sse_event(comment="ping")
                    heartbeat = asyncio.create_task(deps.clock.sleep(15))
        finally:
            for task in (next_event, heartbeat):
                task.cancel()
                with suppress(asyncio.CancelledError, StopAsyncIteration):
                    await task
            await subscription.aclose()

    return EventSourceResponse(stream())
