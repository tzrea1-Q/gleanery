from datetime import date
from pathlib import Path

from sqlalchemy import select

from gleanery.query.filters import (
    ContentFilter,
    ContentSort,
    content_conditions,
    content_order,
    like_pattern,
)
from gleanery.store import open_database
from gleanery.store.models import Content, DatasetItem
from tests.support.library import TZ, seed_library


async def _ids(
    session, dataset_id: int, filter: ContentFilter | None, sort: ContentSort = "added_desc"
) -> list[str]:
    rows = await session.scalars(
        select(Content.platform_id)
        .join(DatasetItem, DatasetItem.content_id == Content.id)
        .where(DatasetItem.dataset_id == dataset_id, *content_conditions(filter, TZ))
        .order_by(*content_order(sort, DatasetItem.added_at))
    )
    return list(rows)


def test_like_pattern_escapes() -> None:
    assert like_pattern("100%_a\\") == "%100\\%\\_a\\\\%"


async def test_filters_and_sort(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        lib = await seed_library(session)
        a = lib.dataset_a
        assert await _ids(session, a, ContentFilter(keyword="续航")) == ["v1"]
        assert await _ids(session, a, ContentFilter(author="作者v2")) == ["v2"]
        assert await _ids(session, a, ContentFilter(completeness="summary")) == ["v2"]
        assert await _ids(session, a, ContentFilter(has_subtitles=True)) == ["v1"]
        assert await _ids(session, a, ContentFilter(min_likes=300), "likes_desc") == ["v1", "v3"]
        assert await _ids(session, a, ContentFilter(min_plays=1)) == ["v2", "v1"]
        days = ContentFilter(published_from=date(2026, 10, 2), published_to=date(2026, 10, 2))
        assert await _ids(session, a, days) == ["v2"]
        assert await _ids(session, a, None, "published_asc") == ["v1", "v2", "v3"]
        assert await _ids(session, lib.dataset_b, None, "published_desc") == ["v3", "v4"]
        assert await _ids(session, lib.dataset_b, None, "plays_desc") == ["v4", "v3"]
        assert ContentFilter().is_empty() and not ContentFilter(min_likes=0).is_empty()
    await db.close()
