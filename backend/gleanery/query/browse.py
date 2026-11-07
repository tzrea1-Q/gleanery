"""浏览和定位共用的排序查询。"""

from datetime import tzinfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.query.filters import ContentFilter, ContentSort, content_conditions, content_order
from gleanery.store.models import Content, DatasetItem


async def content_offset(
    session: AsyncSession,
    dataset_id: int,
    content_id: int,
    filter: ContentFilter,
    sort: ContentSort,
    tz: tzinfo | None,
) -> int | None:
    rows = (
        select(
            Content.id.label("id"),
            (func.row_number().over(order_by=content_order(sort, DatasetItem.added_at)) - 1).label(
                "offset"
            ),
        )
        .join(DatasetItem, DatasetItem.content_id == Content.id)
        .where(DatasetItem.dataset_id == dataset_id, *content_conditions(filter, tz))
        .subquery()
    )
    return await session.scalar(select(rows.c.offset).where(rows.c.id == content_id))
