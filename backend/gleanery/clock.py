from __future__ import annotations

import asyncio
import time


class SystemClock:
    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
