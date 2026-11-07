from __future__ import annotations

import random
from collections.abc import Awaitable, Callable
from typing import Protocol

from gleanery.platforms.errors import PageChanged


class ScrollPage(Protocol):
    async def evaluate(self, expression: str, arg: object = None) -> object: ...


SCROLL = "pixels => window.scrollBy(0, pixels)"
AT_BOTTOM = (
    "() => window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 100"
)


async def scroll_until(
    page: ScrollPage,
    predicate: Callable[[float], Awaitable[bool]],
    *,
    wait: float = 1.5,
    misses: int = 3,
    max_steps: int = 60,
    scroll: str = SCROLL,
    at_bottom: str = AT_BOTTOM,
) -> None:
    """小步往下滚，直到等到预期响应；滚到底后连续 `misses` 次仍没有才判页面改版。

    还没滚到底时没等到响应不算一次：2026-11-02 实测，评论多的视频一页评论远高于三步滚动的
    1700px 左右，下一页要滚到列表底部才加载。`max_steps` 防止页面无限变长时一直滚。
    `scroll` 与 `at_bottom` 换成别的表达式时可以在页面里的某个容器内滚（小红书评论在 `.note-scroller` 里）。
    """
    missed = 0
    for _ in range(max_steps):
        await page.evaluate(scroll, random.randint(500, 600))
        if await predicate(wait):
            return
        # 拿不到位置（比如测试替身返回 None）时按已到底计，退回原来"连续 3 次"的判定。
        if await page.evaluate(at_bottom) is not False:
            missed += 1
            if missed >= misses:
                break
    raise PageChanged("missed_responses")
