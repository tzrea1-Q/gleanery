import asyncio
from pathlib import Path

import pytest

from gleanery.store.db import open_database
from gleanery.store.models import CollectionTask, Dataset, RawCapture
from gleanery.store.retention import (
    PURGE_EVERY_SECONDS,
    RetentionJob,
    purge_all,
    purge_expired,
    retention_days,
    set_retention_days,
    usage,
)


async def seed(session, times: list[int]) -> None:
    session.add(Dataset(id=1, name="测试", created_at=1))
    await session.flush()
    session.add(
        CollectionTask(
            id=1,
            dataset_id=1,
            platform="bili",
            status="done",
            queue_key=1,
            snapshot={},
            progress={},
            created_at=1,
            updated_at=1,
        )
    )
    await session.flush()
    session.add_all(
        [
            RawCapture(
                task_id=1,
                platform="bili",
                kind="test",
                url_path="/",
                captured_at=at,
                body_gz=b"abc",
            )
            for at in times
        ]
    )


async def test_retention_and_usage(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    try:
        async with db.sessionmaker.begin() as session:
            await seed(session, [1, 2, 3])
        async with db.sessionmaker.begin() as session:
            assert await retention_days(session) == 30
            await set_retention_days(session, None)
            assert await retention_days(session) is None
            assert await purge_expired(session, 7 * 86400000 + 2, None) == 0
            assert await purge_expired(session, 7 * 86400000 + 2, 7) == 1
            count, raw_bytes, db_bytes = await usage(session, tmp_path / "gleanery.db")
            assert (count, raw_bytes) == (2, 6)
            assert db_bytes == sum(
                p.stat().st_size
                for p in await asyncio.to_thread(lambda: list(tmp_path.glob("gleanery.db*")))
                if p.name in {"gleanery.db", "gleanery.db-wal", "gleanery.db-shm"}
            )
            assert await purge_all(session) == 2
            with pytest.raises(ValueError):
                await set_retention_days(session, 8)
    finally:
        await db.close()


async def test_job_runs_immediately_and_stops(tmp_path: Path) -> None:
    db = await open_database(tmp_path)

    class Clock:
        def __init__(self) -> None:
            self.sleeping = asyncio.Event()

        def now_ms(self) -> int:
            return 31 * 86400000

        async def sleep(self, seconds: float) -> None:
            assert seconds == PURGE_EVERY_SECONDS
            self.sleeping.set()
            await asyncio.Event().wait()

    clock = Clock()
    try:
        async with db.sessionmaker.begin() as session:
            await seed(session, [1])
        job = RetentionJob(db, clock)
        await job.start()
        await asyncio.wait_for(clock.sleeping.wait(), 5)
        async with db.sessionmaker() as session:
            assert (await usage(session, tmp_path / "gleanery.db"))[0] == 0
        await job.stop()
    finally:
        await db.close()
