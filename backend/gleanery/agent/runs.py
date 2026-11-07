"""对话中各轮 Agent 的互斥与运行状态。"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from typing import Literal

from gleanery.events import EventBus

RunSource = Literal["chat", "follow_up"]

logger = logging.getLogger(__name__)


class ConversationRuns:
    def __init__(self, events: EventBus) -> None:
        self.events = events
        self.locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.running: dict[int, RunSource] = {}
        self.tasks: set[asyncio.Task] = set()
        self.detached: set[int] = set()
        """客户端已断开、仍在后台跑的对话轮次。"""

    def busy(self, conversation_id: int) -> RunSource | None:
        return self.running.get(conversation_id)

    def spawn(self, conversation_id: int, coro: Coroutine[None, None, None]) -> asyncio.Task:
        """对话路由的一轮放到后台任务里跑：客户端断开（如切到别的对话）时照样跑完并落库，
        否则已执行的工具（如开始采集）没有记录，界面上还停在待批准。"""
        task = asyncio.create_task(coro)
        self.tasks.add(task)

        def done(task: asyncio.Task) -> None:
            self.tasks.discard(task)
            self.detached.discard(conversation_id)
            if not task.cancelled() and (error := task.exception()):
                logger.error("对话后台运行失败", exc_info=error)

        task.add_done_callback(done)
        return task

    def detach(self, conversation_id: int, task: asyncio.Task) -> None:
        if not task.done():
            self.detached.add(conversation_id)

    async def close(self) -> None:
        """应用关闭时取消，不落库。"""
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    @asynccontextmanager
    async def hold(self, conversation_id: int, source: RunSource | None) -> AsyncIterator[None]:
        """`source` 为 None 时只排他、不算运行：追加事件消息只占一瞬间，不该让对话返回 409。"""
        async with self.locks[conversation_id]:
            if source is None:
                yield
                return
            async with self.announce(conversation_id, source):
                yield

    @asynccontextmanager
    async def announce(self, conversation_id: int, source: RunSource) -> AsyncIterator[None]:
        """已持有锁时，标记这个对话正在跑一轮 Agent。"""
        self.running[conversation_id] = source
        self.events.publish(
            "conversation.run",
            {"conversation_id": conversation_id, "source": source, "running": True},
        )
        try:
            yield
        finally:
            self.running.pop(conversation_id, None)
            self.events.publish(
                "conversation.run",
                {"conversation_id": conversation_id, "source": source, "running": False},
            )
