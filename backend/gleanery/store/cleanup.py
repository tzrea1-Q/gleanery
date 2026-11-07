"""数据集删除与内容回收；调用方负责提交。"""

from collections.abc import Sequence

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.schemas_data import DataImpact, DeleteImpact, RemoveImpact
from gleanery.store.db import Database
from gleanery.store.models import (
    Author,
    CollectionTask,
    Comment,
    Content,
    Dataset,
    DatasetItem,
    RawCapture,
    Report,
)


class HasActiveTasks(Exception):
    def __init__(self, task_ids: list[int]) -> None:
        super().__init__("有未结束的采集任务")
        self.task_ids = task_ids


async def impact_of_remove(
    session: AsyncSession, dataset_id: int, content_ids: Sequence[int]
) -> RemoveImpact | None:
    if await session.get(Dataset, dataset_id) is None:
        return None
    ids = list(dict.fromkeys(content_ids))
    members = set(
        (
            await session.scalars(
                select(DatasetItem.content_id).where(
                    DatasetItem.dataset_id == dataset_id, DatasetItem.content_id.in_(ids)
                )
            )
        ).all()
    )
    orphan_ids = select(Content.id).where(
        Content.id.in_(members),
        ~select(DatasetItem.content_id)
        .where(DatasetItem.content_id == Content.id, DatasetItem.dataset_id != dataset_id)
        .exists(),
    )
    count = await session.scalar(
        select(func.count()).select_from(Content).where(Content.id.in_(orphan_ids))
    )
    comments = await session.scalar(
        select(func.count()).select_from(Comment).where(Comment.content_id.in_(orphan_ids))
    )
    return RemoveImpact(
        removed=len(members),
        not_member=[i for i in ids if i not in members],
        recycled_contents=count or 0,
        recycled_comments=comments or 0,
    )


async def impact_of_delete(session: AsyncSession, dataset_id: int) -> DeleteImpact | None:
    if await session.get(Dataset, dataset_id) is None:
        return None
    ids = list(
        (
            await session.scalars(
                select(DatasetItem.content_id).where(DatasetItem.dataset_id == dataset_id)
            )
        ).all()
    )
    impact = await impact_of_remove(session, dataset_id, ids)
    assert impact is not None
    comments = await session.scalar(
        select(func.count()).select_from(Comment).where(Comment.content_id.in_(ids))
    )
    tasks = list(
        (
            await session.scalars(
                select(CollectionTask)
                .where(CollectionTask.dataset_id == dataset_id)
                .order_by(CollectionTask.id)
            )
        ).all()
    )
    return DeleteImpact(
        reports=await session.scalar(
            select(func.count()).select_from(Report).where(Report.dataset_id == dataset_id)
        )
        or 0,
        contents=len(ids),
        comments=comments or 0,
        recycled_contents=impact.recycled_contents,
        recycled_comments=impact.recycled_comments,
        tasks=len(tasks),
        active_task_ids=[t.id for t in tasks if t.status in ("queued", "running", "paused")],
    )


async def delete_dataset(session: AsyncSession, dataset_id: int) -> DeleteImpact | None:
    impact = await impact_of_delete(session, dataset_id)
    if impact is None:
        return None
    if impact.active_task_ids:
        raise HasActiveTasks(impact.active_task_ids)
    await session.execute(delete(Dataset).where(Dataset.id == dataset_id))
    await recycle_orphans(session)
    return impact


async def remove_from_dataset(
    session: AsyncSession, dataset_id: int, content_ids: Sequence[int]
) -> RemoveImpact | None:
    impact = await impact_of_remove(session, dataset_id, content_ids)
    if impact is None:
        return None
    await session.execute(
        delete(DatasetItem).where(
            DatasetItem.dataset_id == dataset_id, DatasetItem.content_id.in_(content_ids)
        )
    )
    await recycle_orphans(session)
    return impact


async def recycle_orphans(session: AsyncSession) -> tuple[int, int]:
    orphan = select(Content.id).where(
        ~select(DatasetItem.content_id).where(DatasetItem.content_id == Content.id).exists()
    )
    contents = (
        await session.scalar(
            select(func.count()).select_from(Content).where(Content.id.in_(orphan))
        )
        or 0
    )
    comments = (
        await session.scalar(
            select(func.count()).select_from(Comment).where(Comment.content_id.in_(orphan))
        )
        or 0
    )
    await session.execute(delete(Content).where(Content.id.in_(orphan)))
    await session.execute(
        delete(Author).where(
            ~select(Content.id).where(Content.author_id == Author.id).exists(),
            ~select(Comment.id).where(Comment.author_id == Author.id).exists(),
        )
    )
    return contents, comments


async def impact_of_all(session: AsyncSession) -> DataImpact:
    async def count(model: type) -> int:
        return await session.scalar(select(func.count()).select_from(model)) or 0

    active = list(
        (
            await session.scalars(
                select(CollectionTask.id)
                .where(CollectionTask.status.in_(["queued", "running", "paused"]))
                .order_by(CollectionTask.id)
            )
        ).all()
    )
    return DataImpact(
        datasets=await count(Dataset),
        contents=await count(Content),
        comments=await count(Comment),
        tasks=await count(CollectionTask),
        raw_captures=await count(RawCapture),
        active_task_ids=active,
    )


async def delete_all_collected(session: AsyncSession) -> DataImpact:
    impact = await impact_of_all(session)
    if impact.active_task_ids:
        raise HasActiveTasks(impact.active_task_ids)
    await session.execute(delete(Dataset))
    await session.execute(delete(Content))
    await session.execute(delete(Author))
    return impact


async def vacuum(db: Database) -> None:
    async with db.engine.connect() as connection:
        # 每步只释放一页，要读完结果；SQLAlchemy 当它不返回行，执行一步就关掉了，所以用驱动连接
        raw = (await connection.get_raw_connection()).driver_connection
        assert raw is not None
        async with raw.execute("PRAGMA incremental_vacuum") as cursor:
            await cursor.fetchall()
        await connection.commit()
        await connection.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
