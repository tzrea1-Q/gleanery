"""进程内事件总线 → `GET /api/events` SSE。

前端收到事件后让对应的 TanStack Query 失效并重新拉取，事件本身只带最少的数据。
M0 的事件类型见 `EventType`。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any, Literal

from pydantic import BaseModel

EventType = Literal[
    "conversation.updated",  # data: {conversation_id}，标题、更新时间或消息变了
    "conversation.deleted",  # data: {conversation_id}
    "model_configs.changed",  # data: {}，模型配置、常用模型或测试结果变了
    "app_state.changed",  # data: {}，当前模型或使用声明状态变了
    "plan.updated",  # data: {plan_id}，草稿被改或被确认
    "task.updated",  # data: {task_id, plan_id}，状态、等待原因或进度变了
    "platform.updated",  # data: {platform}，平台状态、探活结果、浏览器启停变了
    "login.updated",  # data: {platform, phase}，扫码登录进度
    "dataset.updated",  # data: {dataset_id}，有内容加入或数据集元信息变了
    "risk_event.created",  # data: {platform, task_id}，前端据此发系统通知
    "dataset.deleted",  # data: {dataset_id}
    "data.cleared",  # data: {}，"删除所有采集数据"之后
    "data_settings.changed",  # data: {}，留存天数或占用空间变了
    "report.updated",  # data: {report_id, version, source}，source 为 agent / user
    "report.deleted",  # data: {report_id}
    "conversation.run",  # data: {conversation_id, source, running}，一轮 Agent 开始或结束
]


class Event(BaseModel):
    id: int
    type: EventType
    data: dict[str, Any]


class EventBus:
    def __init__(self) -> None:
        self._next_id = 1
        self._subscribers: set[asyncio.Queue[Event | None]] = set()
        self._closed = False

    def publish(self, type: EventType, data: dict[str, Any] | None = None) -> Event:
        event = Event(id=self._next_id, type=type, data=data or {})
        self._next_id += 1
        for queue in tuple(self._subscribers):
            if queue.full():
                self._drop(queue)
            else:
                queue.put_nowait(event)
        return event

    def _drop(self, queue: asyncio.Queue[Event | None]) -> None:
        self._subscribers.discard(queue)
        while not queue.empty():
            queue.get_nowait()
        queue.put_nowait(None)

    def close(self) -> None:
        self._closed = True
        for queue in tuple(self._subscribers):
            self._drop(queue)

    async def subscribe(self) -> AsyncGenerator[Event]:
        if self._closed:
            return
        queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=256)
        self._subscribers.add(queue)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    return
                yield event
        finally:
            self._subscribers.discard(queue)
