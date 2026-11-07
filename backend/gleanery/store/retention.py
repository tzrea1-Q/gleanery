"""原始响应留存。"""

import asyncio
import logging
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.deps import Clock
from gleanery.store.cleanup import vacuum
from gleanery.store.db import Database
from gleanery.store.models import RawCapture
from gleanery.store.repo_settings import get_setting, set_setting

RETENTION_KEY = "data.raw_retention_days"
DEFAULT_RETENTION_DAYS = 30
PURGE_EVERY_SECONDS = 6 * 3600
logger = logging.getLogger(__name__)


async def retention_days(session: AsyncSession) -> int | None:
    """None 为永久保留；没设置过时为默认 30 天。"""
    return await get_setting(session, RETENTION_KEY, DEFAULT_RETENTION_DAYS)


async def set_retention_days(session: AsyncSession, days: int | None) -> None:
    if days not in (7, 30, 90, None):
        raise ValueError("留存天数必须为 7、30、90 或永久")
    await set_setting(session, RETENTION_KEY, days)


async def purge_expired(session: AsyncSession, now: int, days: int | None) -> int:
    """删除 `captured_at` 早于 `now - days` 的原始响应，返回条数；days 为 None 时不删。不 commit。"""
    if days is None:
        return 0
    result = await session.execute(
        delete(RawCapture).where(RawCapture.captured_at < now - days * 86400 * 1000)
    )
    return cast(CursorResult[Any], result).rowcount


async def purge_all(session: AsyncSession) -> int:
    result = await session.execute(delete(RawCapture))
    return cast(CursorResult[Any], result).rowcount


async def usage(session: AsyncSession, db_path: Path) -> tuple[int, int, int]:
    """(原始响应条数, 原始响应字节数, 库文件 + WAL + SHM 字节数)。"""
    count, size = (
        await session.execute(
            select(
                func.count(RawCapture.id),
                func.coalesce(func.sum(func.length(RawCapture.body_gz)), 0),
            )
        )
    ).one()

    def file_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except FileNotFoundError:
            return 0

    return (
        count,
        size,
        sum(file_size(Path(f"{db_path}{suffix}")) for suffix in ("", "-wal", "-shm")),
    )


class RetentionJob:
    """启动时清一次，之后每 6 小时清一次；删了数据就 vacuum。"""

    def __init__(self, db: Database, clock: Clock) -> None:
        self.db = db
        self.clock = clock
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while True:
            try:
                async with self.db.sessionmaker.begin() as session:
                    deleted = await purge_expired(
                        session, self.clock.now_ms(), await retention_days(session)
                    )
                if deleted:
                    await vacuum(self.db)
            except Exception:
                logger.exception("原始响应定期清理失败")
            try:
                await self.clock.sleep(PURGE_EVERY_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("原始响应定期清理等待失败")
                return

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
