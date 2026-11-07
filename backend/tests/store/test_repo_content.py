import json
from pathlib import Path

from sqlalchemy import func, select, text

from gleanery.platforms.bili.parser import parse
from gleanery.platforms.types import (
    AuthorRecord,
    Capture,
    CommentRecord,
    ContentRecord,
    Counts,
    SubtitleRecord,
    SubtitleSegment,
)
from gleanery.store import open_database, repo_content
from gleanery.store.models import (
    Author,
    CollectionTask,
    Comment,
    Content,
    ContentMetricSnapshot,
    Dataset,
    Subtitle,
)


async def test_content_merge(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        assert await session.scalar(text("PRAGMA foreign_keys")) == 1
        author = AuthorRecord(platform="bili", platform_id="a", nickname="旧")
        record = ContentRecord(
            platform="bili",
            platform_id="x",
            url="url",
            kind="video",
            title="标题",
            body="正文",
            author=author,
            counts=Counts(likes=2),
            completeness="detail",
            ext={"token": "保留"},
        )
        content_id = (await repo_content.upsert_contents(session, [record], None, 1))["x"]
        comment = CommentRecord(
            platform="bili",
            platform_id="c",
            content_platform_id="x",
            body="旧",
            author=author,
            likes=1,
        )
        await repo_content.upsert_comments(session, content_id, [comment], None, 1)
        await repo_content.upsert_subtitles(
            session,
            content_id,
            [
                SubtitleRecord(
                    content_platform_id="x",
                    part_id="1",
                    lang="zh",
                    ai_generated=False,
                    segments=[
                        SubtitleSegment.model_validate({"from": 0, "to": 1, "content": "字幕"})
                    ],
                )
            ],
            1,
        )
        await repo_content.upsert_contents(
            session,
            [
                record.model_copy(
                    update={
                        "title": None,
                        "body": None,
                        "author": author.model_copy(update={"nickname": "新"}),
                        "counts": Counts(likes=0),
                        "completeness": "summary",
                        "ext": {},
                    }
                )
            ],
            None,
            2,
        )
        await repo_content.upsert_comments(
            session,
            content_id,
            [comment.model_copy(update={"body": "新", "likes": 0, "author": None})],
            None,
            2,
        )
        await session.flush()
        content = await session.get(Content, content_id)
        assert content is not None
        assert (content.title, content.body, content.completeness, content.likes, content.ext) == (
            "标题",
            "正文",
            "detail",
            0,
            {"token": "保留"},
        )
        stored_author = await session.scalar(select(Author))
        assert stored_author is not None and stored_author.nickname == "新"
        stored_comment = await session.scalar(select(Comment))
        assert stored_comment is not None and (stored_comment.body, stored_comment.likes) == (
            "新",
            0,
        )
        assert await session.scalar(select(func.count()).select_from(ContentMetricSnapshot)) == 2
        assert await session.scalar(select(func.count()).select_from(Subtitle)) == 1
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(Content)) == 0
    await db.close()


async def test_task_provenance_and_comments_retained(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        dataset = Dataset(name="测试", description="", created_at=1)
        session.add(dataset)
        await session.flush()
        tasks = [
            CollectionTask(
                dataset_id=dataset.id,
                platform="bili",
                status="done",
                queue_key=index,
                snapshot={},
                progress={},
                created_at=index,
                updated_at=index,
            )
            for index in (1, 2)
        ]
        session.add_all(tasks)
        await session.flush()
        record = ContentRecord(
            platform="bili", platform_id="x", url="url", kind="video", completeness="summary"
        )
        content_id = (await repo_content.upsert_contents(session, [record], tasks[0].id, 1))["x"]
        comments = [
            CommentRecord(platform="bili", platform_id=key, content_platform_id="x", body=key)
            for key in ("a", "b")
        ]
        await repo_content.upsert_comments(session, content_id, comments, tasks[0].id, 1)
        await repo_content.upsert_contents(session, [record], tasks[1].id, 2)
        await repo_content.upsert_comments(session, content_id, comments[:1], tasks[1].id, 2)
        await session.flush()
        content = await session.get(Content, content_id)
        assert content is not None and (content.first_task_id, content.last_task_id) == (
            tasks[0].id,
            tasks[1].id,
        )
        stored = (await session.scalars(select(Comment).order_by(Comment.platform_id))).all()
        assert len(stored) == 2
        assert (stored[0].first_task_id, stored[0].last_task_id) == (tasks[0].id, tasks[1].id)
        assert stored[1].last_task_id == tasks[0].id
    await db.close()


async def test_detail_keeps_search_category_and_tags(tmp_path: Path) -> None:
    root = Path(__file__).parents[1] / "fixtures" / "bili"

    def load(name: str) -> Capture:
        return Capture.model_validate(json.loads((root / name).read_text())["capture"])

    search = parse(load("ssr__search/20261102-tags.json"))
    assert search and search.search
    summary = search.search.contents[0]
    video = load("ssr__video/20261101-normal.json")
    video.body["bvid"] = summary.platform_id
    detail = parse(video)
    assert detail and detail.content and summary.ext["tname"] and summary.tags
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        await repo_content.upsert_contents(session, [summary], None, 1)
        await repo_content.upsert_contents(session, [detail.content], None, 2)
        await repo_content.upsert_contents(
            session, [detail.content.model_copy(update={"platform_id": "BV1only0detail"})], None, 3
        )
        await session.commit()
        rows = (
            await session.execute(
                text("SELECT category, tags, completeness FROM v_contents ORDER BY content_id")
            )
        ).all()
    assert [(row[0], json.loads(row[1]), row[2]) for row in rows] == [
        (summary.ext["tname"], summary.tags, "detail"),
        # 只经过详情阶段（按链接采集）的内容取不到分区，写 NULL 而不是空串。
        (None, [], "detail"),
    ]
    await db.close()
