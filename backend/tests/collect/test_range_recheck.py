from pathlib import Path

import pytest
from sqlalchemy import select

from gleanery.collect import worker
from gleanery.collect.plan import PlatformSection
from gleanery.platforms.types import (
    CollectResult,
    CommentRecord,
    Depth,
    ParseReport,
    SearchPage,
    SubtitleRecord,
    TimeRange,
)
from gleanery.store import repo_content, repo_datasets
from gleanery.store.models import (
    CollectionTask,
    Comment,
    Content,
    DatasetItem,
    PlatformState,
    Subtitle,
    TaskItem,
)
from tests.collect.test_worker_scenarios import record, setup


@pytest.mark.parametrize("previous_member,has_range", [(False, True), (True, True), (False, False)])
async def test_detail_range_recheck(tmp_path: Path, previous_member: bool, has_range: bool) -> None:
    section = PlatformSection(
        platform="xhs",
        keywords=["a"],
        quantity=2,
        depth=Depth(detail=True),
        time_range=TimeRange(last_days=1) if has_range else None,
    )
    db, service, fetcher, clock = await setup(tmp_path, section)
    fetcher.pages = {
        "a": [
            SearchPage(
                contents=[
                    record(name).model_copy(update={"platform": "xhs", "published_at": clock.now})
                    for name in ("a", "b")
                ],
                has_more=False,
                report=ParseReport(items=2),
            )
        ]
    }

    async def detail(ref, depth, ctx):
        published_at = clock.now - 86_400_000 if ref.platform_id == "a" else clock.now
        return CollectResult(
            content=record(ref.platform_id).model_copy(
                update={"platform": "xhs", "published_at": published_at, "completeness": "detail"}
            ),
            comments=[
                CommentRecord(
                    platform="xhs",
                    platform_id=ref.platform_id,
                    content_platform_id=ref.platform_id,
                    body="评论",
                )
            ],
            subtitles=[
                SubtitleRecord(
                    content_platform_id=ref.platform_id,
                    part_id="1",
                    lang="zh",
                    ai_generated=False,
                    segments=[],
                )
            ],
            report=ParseReport(items=1),
        )

    fetcher.collect_content = detail
    try:
        async with db.sessionmaker.begin() as session:
            current = await session.get(CollectionTask, 1)
            assert current is not None
            current.platform = "xhs"
        if previous_member:
            async with db.sessionmaker.begin() as session:
                current = await session.get(CollectionTask, 1)
                assert current is not None
                session.add(
                    CollectionTask(
                        id=2,
                        dataset_id=1,
                        platform="xhs",
                        status="completed",
                        queue_key=2,
                        snapshot=current.snapshot,
                        progress=current.progress,
                        created_at=clock.now,
                        updated_at=clock.now,
                    )
                )
                await session.flush()
                existing = record("a").model_copy(update={"platform": "xhs"})
                ids = await repo_content.upsert_contents(session, [existing], 2, clock.now)
                await repo_datasets.add_to_dataset(session, 1, [ids["a"]], 2, clock.now)
        await worker.execute(service, "xhs", 1)
        async with db.sessionmaker() as session:
            task = await session.get(CollectionTask, 1)
            state = await session.get(PlatformState, "xhs")
            items = list(await session.scalars(select(TaskItem).order_by(TaskItem.platform_id)))
            members = (
                await session.execute(
                    select(Content.platform_id, DatasetItem.task_id).join(DatasetItem)
                )
            ).all()
            assert task is not None and task.status == "completed"
            assert state is not None and state.quota_used == 2
            assert task.progress["quota_counted"] == 2
            assert task.progress["comments"] == 2 and task.progress["subtitles"] == 2
            assert task.progress["processed"] == (1 if has_range else 2)
            assert [(item.state, item.skip_reason) for item in items] == [
                ("skipped", "out_of_range") if has_range else ("done", None),
                ("done", None),
            ]
            assert all(item.content_id is not None for item in items)
            assert set(members) == (
                {("b", 1), ("a", 2)}
                if previous_member
                else ({("b", 1)} if has_range else {("a", 1), ("b", 1)})
            )
            assert len(list(await session.scalars(select(Content)))) == 2
            assert len(list(await session.scalars(select(Comment)))) == 2
            assert len(list(await session.scalars(select(Subtitle)))) == 2
    finally:
        await db.close()
