from pathlib import Path

from gleanery.platforms.types import ContentRecord
from gleanery.store import open_database, repo_content, repo_datasets


async def test_dataset_contents(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        dataset = await repo_datasets.create_dataset(session, "测试", "", None, 1)
        record = ContentRecord(
            platform="bili",
            platform_id="x",
            url="url",
            kind="video",
            body="字" * 130,
            completeness="detail",
            ext={"counts_approx": True},
        )
        content_id = (await repo_content.upsert_contents(session, [record], None, 1))["x"]
        await repo_datasets.add_to_dataset(session, dataset.id, [content_id, content_id], None, 2)
        result = await repo_datasets.get(session, dataset.id)
        assert result is not None and result.counts == {"bili": 1} and result.total == 1
        page = await repo_datasets.contents_page(session, dataset.id, 50, 0)
        assert page.total == 1 and page.items[0].body_excerpt == "字" * 120
        assert page.items[0].counts_approx and page.items[0].local_comments == 0
        assert len(await repo_datasets.list_all(session)) == 1
        await session.rollback()
    await db.close()
