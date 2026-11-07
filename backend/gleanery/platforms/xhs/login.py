"""小红书扫码登录与预热。

游客打开首页时页面自己弹出扫码框（2026-11-03 实测），所以不点任何按钮。游客配置目录里也有
`web_session` 这个 Cookie 名，Cookie 名不能当登录信号；初判读页面状态里的 `user.loggedIn`，
复核在下一次整页导航后读 SSR。
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Literal

from gleanery.deps import Clock
from gleanery.platforms.errors import PageChanged, RiskDetected
from gleanery.platforms.types import Capture
from gleanery.platforms.xhs import selectors
from gleanery.platforms.xhs.driver import Page
from gleanery.platforms.xhs.risk import judge

LoginPhase = Literal["waiting_scan", "verifying", "succeeded", "timeout"]


def _logged_in(state: object) -> bool:
    return isinstance(state, dict) and state.get("logged_in") is True and not state.get("guest")


async def login(page: Page, clock: Clock, callback: Callable[[LoginPhase], None]) -> bool:
    await page.goto(selectors.HOME, wait_until="domcontentloaded")
    callback("waiting_scan")
    deadline = clock.now_ms() + 600_000
    while clock.now_ms() < deadline:
        if _logged_in(await page.evaluate(selectors.USER_STATE)):
            callback("verifying")
            await page.goto(selectors.HOME, wait_until="domcontentloaded")
            state = None
            for _ in range(20):
                state = await page.evaluate(selectors.USER_STATE)
                if state is not None:
                    break
                await clock.sleep(0.5)
            if state is None:
                raise PageChanged("missing_ssr", selectors.SSR_USER)
            verdict = judge(
                Capture(
                    platform="xhs",
                    kind=selectors.SSR_USER,
                    url_path="/explore",
                    body=state,
                    captured_at=clock.now_ms(),
                )
            )
            if verdict:
                raise RiskDetected(verdict)
            callback("succeeded")
            return True
        await clock.sleep(1)
    callback("timeout")
    return False


async def warmup(page: Page, minutes: float, clock: Clock) -> None:
    await page.goto(selectors.HOME, wait_until="domcontentloaded")
    deadline = clock.now_ms() + int(minutes * 60_000)
    while clock.now_ms() < deadline:
        await clock.sleep(min(5, (deadline - clock.now_ms()) / 1000))
        if clock.now_ms() < deadline:
            await page.evaluate("pixels => window.scrollBy(0, pixels)", random.randint(500, 600))
