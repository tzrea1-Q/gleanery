from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from typing import Any, Literal

from gleanery.deps import Clock
from gleanery.platforms.bili import selectors
from gleanery.platforms.bili.driver import Page
from gleanery.platforms.bili.risk import judge
from gleanery.platforms.errors import PageChanged, RiskDetected
from gleanery.platforms.types import Capture

LoginPhase = Literal["waiting_scan", "verifying", "succeeded", "timeout"]


async def login(page: Page, clock: Clock, callback: Callable[[LoginPhase], None]) -> bool:
    await page.goto(selectors.HOME, wait_until="domcontentloaded")
    await page.locator(selectors.LOGIN_BUTTON).click()
    callback("waiting_scan")
    deadline = clock.now_ms() + 600_000
    while clock.now_ms() < deadline:
        if any(cookie.get("name") == "SESSDATA" for cookie in await page.context.cookies()):
            callback("verifying")
            loop = asyncio.get_running_loop()
            nav: asyncio.Future[Capture] = loop.create_future()

            tasks: list[asyncio.Task[None]] = []

            def on_response(
                response: Any,
                future: asyncio.Future[Capture] = nav,
                pending: list[asyncio.Task[None]] = tasks,
            ) -> None:
                async def read() -> None:
                    try:
                        body = await response.json()
                    except Exception:
                        body = await response.text()
                    if not future.done():
                        future.set_result(
                            Capture(
                                platform="bili",
                                kind=selectors.NAV,
                                url_path="/" + selectors.NAV,
                                status=response.status,
                                body=body,
                                captured_at=clock.now_ms(),
                            )
                        )

                if str(response.url).split("?", 1)[0].endswith("/" + selectors.NAV):
                    pending.append(asyncio.create_task(read()))

            page.on("response", on_response)
            try:
                await page.goto(selectors.HOME, wait_until="domcontentloaded")
                try:
                    capture = await asyncio.wait_for(nav, 10)
                except TimeoutError as exc:
                    raise PageChanged("missing_nav") from exc
                verdict = judge(capture)
                if verdict:
                    raise RiskDetected(verdict)
            finally:
                page.remove_listener("response", on_response)
                if tasks:
                    await asyncio.gather(*tasks)
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
