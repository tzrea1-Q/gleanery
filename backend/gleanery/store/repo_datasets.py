from collections.abc import Sequence
from datetime import tzinfo
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.schemas_collect import ContentPage, ContentRow, DatasetOut
from gleanery.platforms.links import open_url
from gleanery.platforms.types import Completeness, Platform
from gleanery.query.filters import ContentFilter, ContentSort, content_conditions, content_order
from gleanery.store.models import Author, Comment, Content, Dataset, DatasetItem, Subtitle


async def create_dataset(
    session: AsyncSession,
    name: str,
    description: str,
    created_in_conversation_id: int | None,
    now: int,
) -> Dataset:
    dataset = Dataset(
        name=name,
        description=description,
        created_in_conversation_id=created_in_conversation_id,
        created_at=now,
    )
    session.add(dataset)
    await session.flush()
    return dataset


async def get(session: AsyncSession, dataset_id: int) -> DatasetOut | None:
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None:
        return None
    rows = await session.execute(
        select(Content.platform, func.count())
        .join(DatasetItem, DatasetItem.content_id == Content.id)
        .where(DatasetItem.dataset_id == dataset_id)
        .group_by(Content.platform)
    )
    counts = dict(rows.all())
    return DatasetOut(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        created_in_conversation_id=dataset.created_in_conversation_id,
        counts=counts,
        total=sum(counts.values()),
        created_at=dataset.created_at,
        last_appended_at=dataset.last_appended_at,
    )


async def list_all(session: AsyncSession) -> list[DatasetOut]:
    ids = (
        await session.scalars(
            select(Dataset.id).order_by(Dataset.created_at.desc(), Dataset.id.desc())
        )
    ).all()
    return [item for dataset_id in ids if (item := await get(session, dataset_id)) is not None]


async def add_to_dataset(
    session: AsyncSession,
    dataset_id: int,
    content_ids: Sequence[int],
    task_id: int | None,
    now: int,
) -> None:
    for content_id in content_ids:
        await session.execute(
            insert(DatasetItem)
            .values(dataset_id=dataset_id, content_id=content_id, task_id=task_id, added_at=now)
            .on_conflict_do_nothing()
        )
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None:
        raise ValueError("数据集不存在")
    dataset.last_appended_at = now


async def contents_page(
    session: AsyncSession,
    dataset_id: int,
    limit: int,
    offset: int,
    filter: ContentFilter | None = None,
    sort: ContentSort = "added_desc",
    tz: tzinfo | None = None,
) -> ContentPage:
    total = await session.scalar(
        select(func.count()).select_from(DatasetItem).where(DatasetItem.dataset_id == dataset_id)
    )
    conditions = [DatasetItem.dataset_id == dataset_id, *content_conditions(filter, tz)]
    filtered_total = await session.scalar(
        select(func.count())
        .select_from(Content)
        .join(DatasetItem, DatasetItem.content_id == Content.id)
        .where(*conditions)
    )
    comment_count = (
        select(func.count())
        .select_from(Comment)
        .where(Comment.content_id == Content.id)
        .scalar_subquery()
    )
    subtitle_count = (
        select(func.count())
        .select_from(Subtitle)
        .where(Subtitle.content_id == Content.id)
        .scalar_subquery()
    )
    rows = await session.execute(
        select(Content, Author.nickname, DatasetItem.added_at, comment_count, subtitle_count)
        .join(DatasetItem, DatasetItem.content_id == Content.id)
        .outerjoin(Author, Author.id == Content.author_id)
        .where(*conditions)
        .order_by(*content_order(sort, DatasetItem.added_at))
        .limit(limit)
        .offset(offset)
    )
    return ContentPage(
        total=total or 0,
        filtered_total=filtered_total or 0,
        items=[
            ContentRow(
                id=content.id,
                platform=cast(Platform, content.platform),
                url=content.url,
                open_url=open_url(cast(Platform, content.platform), content.url, content.ext),
                kind=content.kind,
                title=content.title,
                body_excerpt=content.body[:120] if content.body is not None else None,
                author_nickname=nickname,
                published_at=content.published_at,
                likes=content.likes,
                comments=content.comments,
                plays=content.plays,
                counts_approx=bool(content.ext.get("counts_approx", False)),
                completeness=cast(Completeness, content.completeness),
                local_comments=local_comments,
                subtitles=subtitles,
                added_at=added_at,
            )
            for content, nickname, added_at, local_comments, subtitles in rows
        ],
    )
