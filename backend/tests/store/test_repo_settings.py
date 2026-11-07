import asyncio
from pathlib import Path

from gleanery.store import open_database
from gleanery.store.repo_settings import get_setting, set_setting


async def test_concurrent_first_writes_do_not_collide(tmp_path: Path) -> None:
    # 两个会话同时首次写同一个键、写完稍等再提交：先查后插的写法第二次提交会撞主键。
    db = await open_database(tmp_path)

    async def write(value: int) -> None:
        async with db.sessionmaker() as session:
            await set_setting(session, "k", value)
            await asyncio.sleep(0.05)
            await session.commit()

    await asyncio.gather(write(1), write(2))
    async with db.sessionmaker() as session:
        assert await get_setting(session, "k") in (1, 2)
    await db.close()


async def test_set_refreshes_loaded_row(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        await set_setting(session, "k", {"a": 1})
        assert await get_setting(session, "k") == {"a": 1}
        await set_setting(session, "k", {"a": 2})
        assert await get_setting(session, "k") == {"a": 2}
    await db.close()
