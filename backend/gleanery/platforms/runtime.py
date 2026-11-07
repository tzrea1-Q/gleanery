"""真实的平台运行时：专用浏览器 + 各平台的取数器、扫码登录、预热。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, cast

from gleanery.browser.manager import BrowserManager
from gleanery.collect.runtime import RuntimeLoginPhase
from gleanery.deps import Clock
from gleanery.platforms.bili import login as bili_login
from gleanery.platforms.bili.fetcher import BiliFetcher
from gleanery.platforms.types import Fetcher, Platform
from gleanery.platforms.xhs import login as xhs_login
from gleanery.platforms.xhs.fetcher import XhsFetcher


class BrowserRuntime:
    platforms: frozenset[Platform] = frozenset({"bili", "xhs"})

    def __init__(self, manager: BrowserManager, clock: Clock) -> None:
        self.manager = manager
        self.clock = clock

    def _check(self, platform: Platform) -> None:
        if platform not in self.platforms:
            raise ValueError(f"{platform} 还没有取数实现")

    def fetcher(self, platform: Platform) -> Fetcher:
        self._check(platform)
        return BiliFetcher(self.manager) if platform == "bili" else XhsFetcher(self.manager)

    async def login(
        self, platform: Platform, callback: Callable[[RuntimeLoginPhase], None]
    ) -> bool:
        self._check(platform)
        async with self.manager.page(platform) as page:
            # 驱动只依赖 Playwright Page 的一小部分，见各平台 driver.py 的 Page 协议。
            module = bili_login if platform == "bili" else xhs_login
            return await module.login(cast(Any, page), self.clock, callback)

    async def warmup(self, platform: Platform, minutes: float) -> None:
        self._check(platform)
        async with self.manager.page(platform) as page:
            module = bili_login if platform == "bili" else xhs_login
            await module.warmup(cast(Any, page), minutes, self.clock)

    def browser_running(self, platform: Platform) -> bool:
        return self.manager.is_running(platform)

    def browser_kind(self, platform: Platform) -> Literal["chrome", "edge", "chromium"] | None:
        return self.manager.browser_kind(platform)

    async def close(self) -> None:
        await self.manager.close_all()
