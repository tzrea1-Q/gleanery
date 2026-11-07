"""取数器打开一次内容页时用的记录器：转交给任务的 sink，同时留一份给本次解析。"""

from __future__ import annotations

from gleanery.platforms.types import Capture, CaptureSink, FetchContext, Pacer


class Recorder:
    def __init__(self, ctx: FetchContext) -> None:
        self.inner = ctx.sink
        self.pacer: Pacer = ctx.pacer
        self.sink: CaptureSink = self
        self.captures: list[Capture] = []
        self._ctx = ctx

    async def save(self, capture: Capture) -> None:
        self.captures.append(capture)
        await self.inner.save(capture)

    def log(self, message: str) -> None:
        self._ctx.log(message)
