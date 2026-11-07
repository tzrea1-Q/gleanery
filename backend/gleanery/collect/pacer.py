from __future__ import annotations

import random

from gleanery.collect.types import RateLimits
from gleanery.deps import Clock
from gleanery.platforms.types import PaceKind


class Pacer:
    def __init__(self, clock: Clock, limits: RateLimits) -> None:
        self.clock = clock
        self.limits = limits

    async def wait(self, kind: PaceKind) -> None:
        interval = (
            self.limits.page_interval if kind == "page" else self.limits.comment_page_interval
        )
        await self.clock.sleep(random.uniform(*interval))

    async def long_rest(self) -> None:
        await self.clock.sleep(random.uniform(*self.limits.long_rest))
