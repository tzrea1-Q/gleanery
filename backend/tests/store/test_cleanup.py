from sqlalchemy import func, select

from gleanery.store import cleanup
from gleanery.store.db import open_database
from gleanery.store.models import Author, Comment, Content, ContentMetricSnapshot, Subtitle
from tests.support.library import seed_library


async def test_delete_and_remove_recycle_orphans(tmp_path):
    db = await open_database(tmp_path)
    try:
        async with db.sessionmaker() as session:
            lib = await seed_library(session)
            session.add(ContentMetricSnapshot(content_id=lib.contents["v1"], observed_at=1))
            await session.commit()
            impact = await cleanup.delete_dataset(session, lib.dataset_a)
            assert impact is not None
            assert (
                impact.contents,
                impact.comments,
                impact.recycled_contents,
                impact.recycled_comments,
            ) == (3, 5, 2, 4)
            assert await session.get(Content, lib.contents["v3"]) is not None
            assert await session.get(Comment, lib.comments["c3"]) is not None
            assert await session.get(Content, lib.contents["v1"]) is None
            assert await session.scalar(select(func.count()).select_from(Subtitle)) == 0
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ContentMetricSnapshot)
                    .where(
                        ContentMetricSnapshot.content_id.in_(
                            [lib.contents["v1"], lib.contents["v2"]]
                        )
                    )
                )
                == 0
            )
            assert await session.scalar(select(func.count()).select_from(Author)) == 4
            await session.rollback()
            assert await session.get(Content, lib.contents["v1"]) is not None
            removed = await cleanup.remove_from_dataset(
                session, lib.dataset_a, [lib.contents["v1"], lib.contents["v3"]]
            )
            assert removed is not None
            assert (removed.removed, removed.recycled_contents, removed.recycled_comments) == (
                2,
                1,
                4,
            )
            await session.commit()
            assert await session.get(Content, lib.contents["v3"]) is not None
            assert await session.get(Content, lib.contents["v1"]) is None
    finally:
        await db.close()


async def test_vacuum_frees_every_page(tmp_path):
    """2026-11-02 M2 冒烟：PRAGMA incremental_vacuum 每步只释放一页，不读完结果只回收了一页。"""
    from sqlalchemy import text

    db = await open_database(tmp_path)
    try:
        async with db.engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO conversation (id, created_at, updated_at) VALUES (1, 1, 1)")
            )
            for seq in range(200):
                await connection.execute(
                    text(
                        "INSERT INTO message (conversation_id, seq, kind, payload, created_at) "
                        "VALUES (1, :seq, 'request', :payload, 1)"
                    ),
                    {"seq": seq, "payload": '"' + "字" * 4000 + '"'},
                )
            await connection.execute(text("DELETE FROM conversation WHERE id = 1"))
        async with db.engine.connect() as connection:
            freed = (await connection.execute(text("PRAGMA freelist_count"))).scalar_one()
        assert freed > 100
        await cleanup.vacuum(db)
        async with db.engine.connect() as connection:
            assert (await connection.execute(text("PRAGMA freelist_count"))).scalar_one() == 0
    finally:
        await db.close()
