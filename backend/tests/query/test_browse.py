from pathlib import Path

from gleanery.query.browse import content_offset
from gleanery.query.filters import ContentFilter
from gleanery.store import open_database, repo_datasets
from tests.support.library import TZ, seed_library


async def test_filter_order_and_locate(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        library = await seed_library(session)
        f = ContentFilter(keyword="耳机")
        page = await repo_datasets.contents_page(session, library.dataset_a, 20, 0, f, "likes_desc")
        assert page.total == 3
        assert page.filtered_total == 2
        assert [row.id for row in page.items] == [library.contents["v1"], library.contents["v2"]]
        assert (
            await content_offset(
                session, library.dataset_a, library.contents["v2"], f, "likes_desc", TZ
            )
            == 1
        )
        assert (
            await content_offset(
                session, library.dataset_a, library.contents["v3"], f, "likes_desc", TZ
            )
            is None
        )
    await db.close()
