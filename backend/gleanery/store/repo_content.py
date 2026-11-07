from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.platforms.types import AuthorRecord, CommentRecord, ContentRecord, SubtitleRecord
from gleanery.store.models import Author, Comment, Content, ContentMetricSnapshot, Subtitle


async def _author(session: AsyncSession, record: AuthorRecord | None, now: int) -> int | None:
    if record is None:
        return None
    author = await session.scalar(
        select(Author).where(
            Author.platform == record.platform, Author.platform_id == record.platform_id
        )
    )
    if author is None:
        author = Author(
            platform=record.platform,
            platform_id=record.platform_id,
            created_at=now,
            updated_at=now,
            ext={},
        )
        session.add(author)
    for field in ("nickname", "avatar_url"):
        value = getattr(record, field)
        if value:
            setattr(author, field, value)
    author.ext = {
        **author.ext,
        **{key: value for key, value in record.ext.items() if value is not None},
    }
    author.updated_at = now
    await session.flush()
    return author.id


async def upsert_contents(
    session: AsyncSession, records: Sequence[ContentRecord], task_id: int | None, now: int
) -> dict[str, int]:
    result: dict[str, int] = {}
    for record in records:
        content = await session.scalar(
            select(Content).where(
                Content.platform == record.platform, Content.platform_id == record.platform_id
            )
        )
        if content is None:
            content = Content(
                platform=record.platform,
                platform_id=record.platform_id,
                url=record.url,
                kind=record.kind,
                completeness=record.completeness,
                first_task_id=task_id,
                created_at=now,
                updated_at=now,
                tags=[],
                ext={},
            )
            session.add(content)
        author_id = await _author(session, record.author, now)
        for field in (
            "url",
            "kind",
            "title",
            "body",
            "published_at",
            "platform_updated_at",
            "tags",
        ):
            value = getattr(record, field)
            if value is not None and value != "" and value != []:
                setattr(content, field, value)
        if author_id is not None:
            content.author_id = author_id
        if record.completeness == "detail":
            content.completeness = "detail"
        counts = record.counts.model_dump()
        for field, value in counts.items():
            if value is not None:
                setattr(content, field, value)
        content.ext = {
            **content.ext,
            **{key: value for key, value in record.ext.items() if value is not None},
        }
        content.metrics_observed_at = now
        content.last_task_id = task_id
        content.updated_at = now
        await session.flush()
        session.add(
            ContentMetricSnapshot(content_id=content.id, observed_at=now, task_id=task_id, **counts)
        )
        result[record.platform_id] = content.id
    return result


async def upsert_comments(
    session: AsyncSession,
    content_id: int,
    records: Sequence[CommentRecord],
    task_id: int | None,
    now: int,
) -> None:
    for record in records:
        comment = await session.scalar(
            select(Comment).where(
                Comment.platform == record.platform, Comment.platform_id == record.platform_id
            )
        )
        if comment is None:
            comment = Comment(
                platform=record.platform,
                platform_id=record.platform_id,
                content_id=content_id,
                body=record.body,
                first_task_id=task_id,
                created_at=now,
                updated_at=now,
                ext={},
            )
            session.add(comment)
        author_id = await _author(session, record.author, now)
        for field in (
            "root_platform_id",
            "parent_platform_id",
            "body",
            "published_at",
            "likes",
            "reply_count",
            "ip_location",
        ):
            value = getattr(record, field)
            if value is not None and value != "":
                setattr(comment, field, value)
        if author_id is not None:
            comment.author_id = author_id
        comment.ext = {
            **comment.ext,
            **{key: value for key, value in record.ext.items() if value is not None},
        }
        comment.last_task_id = task_id
        comment.updated_at = now


async def upsert_subtitles(
    session: AsyncSession, content_id: int, records: Sequence[SubtitleRecord], now: int
) -> None:
    for record in records:
        subtitle = await session.scalar(
            select(Subtitle).where(
                Subtitle.content_id == content_id,
                Subtitle.part_id == record.part_id,
                Subtitle.lang == record.lang,
            )
        )
        if subtitle is None:
            subtitle = Subtitle(
                content_id=content_id, part_id=record.part_id, lang=record.lang, created_at=now
            )
            session.add(subtitle)
        subtitle.part_title = record.part_title
        subtitle.ai_generated = record.ai_generated
        subtitle.text = record.text
        subtitle.segments = [segment.model_dump(by_alias=True) for segment in record.segments]
        subtitle.updated_at = now
