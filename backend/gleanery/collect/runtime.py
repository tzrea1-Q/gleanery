"""平台运行时：执行器和登录编排经它拿到取数器、扫码登录和预热。

真实现由浏览器管理、驱动、解析器和风控判定组装；
测试注入假的。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Protocol

from gleanery.platforms.types import Fetcher, Platform

RuntimeLoginPhase = Literal["waiting_scan", "verifying", "succeeded", "timeout"]


class PlatformRuntime(Protocol):
    platforms: frozenset[Platform]
    """有取数实现的平台；执行器只为这些平台起 worker。"""

    def fetcher(self, platform: Platform) -> Fetcher:
        """新建一个取数器，用完调 `close()`。浏览器按需懒启动。"""
        ...

    async def login(
        self, platform: Platform, callback: Callable[[RuntimeLoginPhase], None]
    ) -> bool:
        """打开登录页由用户扫码，成功返回 True、超时返回 False；浏览器异常照常抛出。"""
        ...

    async def warmup(self, platform: Platform, minutes: float) -> None:
        """登录后预热：只打开首页，停留并小步滚动。"""
        ...

    def browser_running(self, platform: Platform) -> bool: ...

    def browser_kind(self, platform: Platform) -> Literal["chrome", "edge", "chromium"] | None: ...

    async def close(self) -> None:
        """应用退出时关闭全部浏览器。"""
        ...
