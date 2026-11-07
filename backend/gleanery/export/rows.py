"""在数据库会话中读取导出数据。"""

from dataclasses import dataclass
from datetime import tzinfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.query.filters import ContentFilter, ContentSort, content_conditions, content_order
from gleanery.store.models import Author, Comment, Content, Dataset, DatasetItem, Subtitle


@dataclass
class ExportData:
    dataset: Dataset
    contents: list[tuple[Content, int]]
    comments: list[Comment]
    subtitles: list[Subtitle]
    authors: dict[int, str]


async def load(
    session: AsyncSession,
    dataset_id: int,
    filter: ContentFilter | None,
    sort: ContentSort,
    tz: tzinfo | None,
) -> ExportData | None:
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None:
        return None
    result = await session.execute(
        select(Content, DatasetItem.added_at)
        .join(DatasetItem, DatasetItem.content_id == Content.id)
        .where(DatasetItem.dataset_id == dataset_id, *content_conditions(filter, tz))
        .order_by(*content_order(sort, DatasetItem.added_at))
    )
    contents = [(c, added) for c, added in result.all()]
    ids = [c.id for c, _ in contents]
    comments = list(
        (await session.scalars(select(Comment).where(Comment.content_id.in_(ids)))).all()
    )
    subtitles = list(
        (
            await session.scalars(
                select(Subtitle).where(Subtitle.content_id.in_(ids)).order_by(Subtitle.id)
            )
        ).all()
    )
    author_ids = {c.author_id for c, _ in contents} | {c.author_id for c in comments}
    authors = {
        a.id: a.nickname or ""
        for a in (await session.scalars(select(Author).where(Author.id.in_(author_ids)))).all()
    }
    return ExportData(dataset, contents, comments, subtitles, authors)
