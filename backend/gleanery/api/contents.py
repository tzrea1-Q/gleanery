"""内容详情、评论与跳转定位。"""

from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.deps import get_session
from gleanery.api.errors import ApiError, ErrorBody
from gleanery.api.schemas_data import (
    CommentLocate,
    CommentOut,
    CommentPage,
    ContentDetail,
    DatasetRef,
    LocateOut,
    SubtitleOut,
)
from gleanery.platforms.types import Completeness, Platform
from gleanery.store.models import Author, Comment, Content, Dataset, DatasetItem, Subtitle

router = APIRouter(prefix="/api", tags=["contents"])
_404: dict[int | str, dict[str, Any]] = {404: {"model": ErrorBody}}
CommentSort = Literal["likes", "time"]


async def require(session: AsyncSession, model: type[Content] | type[Comment], id: int) -> Any:
    item = await session.get(model, id)
    if item is None:
        raise ApiError(
            404,
            "CONTENT_NOT_FOUND" if model is Content else "COMMENT_NOT_FOUND",
            "内容不存在" if model is Content else "评论不存在",
        )
    return item


def comment_order(sort: CommentSort) -> list[Any]:
    return [
        (Comment.likes if sort == "likes" else Comment.published_at).desc().nulls_last(),
        Comment.id.desc(),
    ]


@router.get("/contents/{content_id}", response_model=ContentDetail, responses=_404)
async def get_content(
    content_id: int, session: Annotated[AsyncSession, Depends(get_session)]
) -> ContentDetail:
    c: Content = await require(session, Content, content_id)
    author = await session.get(Author, c.author_id) if c.author_id else None
    subtitles = (
        await session.scalars(select(Subtitle).where(Subtitle.content_id == content_id))
    ).all()
    datasets = (
        await session.scalars(
            select(Dataset)
            .join(DatasetItem)
            .where(DatasetItem.content_id == content_id)
            .order_by(Dataset.last_appended_at.desc().nulls_last(), Dataset.id.desc())
        )
    ).all()
    count = await session.scalar(
        select(func.count()).select_from(Comment).where(Comment.content_id == content_id)
    )
    return ContentDetail(
        id=c.id,
        platform=cast(Platform, c.platform),
        url=c.url,
        kind=c.kind,
        title=c.title,
        body=c.body,
        author_id=c.author_id,
        author_nickname=author.nickname if author else None,
        published_at=c.published_at,
        platform_updated_at=c.platform_updated_at,
        likes=c.likes,
        favorites=c.favorites,
        comments=c.comments,
        shares=c.shares,
        plays=c.plays,
        coins=c.ext.get("coins"),
        danmaku=c.ext.get("danmaku"),
        duration_seconds=c.ext.get("duration"),
        category=c.ext.get("tname"),
        counts_approx=bool(c.ext.get("counts_approx")),
        tags=c.tags,
        completeness=cast(Completeness, c.completeness),
        local_comments=count or 0,
        subtitles=[
            SubtitleOut(
                id=s.id,
                part_id=s.part_id,
                part_title=s.part_title,
                lang=s.lang,
                ai_generated=s.ai_generated,
                chars=len(s.text),
                text=s.text,
            )
            for s in subtitles
        ],
        datasets=[DatasetRef(id=d.id, name=d.name) for d in datasets],
    )


@router.get("/contents/{content_id}/comments", response_model=CommentPage, responses=_404)
async def list_comments(
    content_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    sort: CommentSort = "likes",
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CommentPage:
    """一级评论分页，每条带本地全部回复。"""
    await require(session, Content, content_id)
    rows = (
        await session.execute(
            select(Comment, Author.nickname)
            .outerjoin(Author)
            .where(Comment.content_id == content_id)
        )
    ).all()
    by_platform = {c.platform_id: c.id for c, _ in rows}

    def out(c: Comment, nickname: str | None) -> CommentOut:
        return CommentOut(
            id=c.id,
            content_id=c.content_id,
            root_comment_id=by_platform.get(c.root_platform_id or ""),
            parent_comment_id=by_platform.get(c.parent_platform_id or ""),
            author_nickname=nickname,
            body=c.body,
            published_at=c.published_at,
            likes=c.likes,
            reply_count=c.reply_count,
            ip_location=c.ip_location,
        )

    roots = (
        await session.scalars(
            select(Comment)
            .where(Comment.content_id == content_id, Comment.root_platform_id.is_(None))
            .order_by(*comment_order(sort))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    names = {c.id: name for c, name in rows}
    items = []
    for root in roots:
        item = out(root, names[root.id])
        replies = [(c, name) for c, name in rows if c.root_platform_id == root.platform_id]
        replies.sort(
            key=lambda row: (row[0].published_at is None, row[0].published_at or 0, row[0].id)
        )
        item.replies = [out(c, name) for c, name in replies]
        items.append(item)
    return CommentPage(
        total=sum(c.root_platform_id is None for c, _ in rows),
        replies_total=sum(c.root_platform_id is not None for c, _ in rows),
        items=items,
    )


@router.get("/comments/{comment_id}/locate", response_model=CommentLocate, responses=_404)
async def locate_comment(
    comment_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    sort: CommentSort = "likes",
) -> CommentLocate:
    c: Comment = await require(session, Comment, comment_id)
    root = (
        c
        if c.root_platform_id is None
        else await session.scalar(
            select(Comment).where(
                Comment.content_id == c.content_id,
                Comment.platform == c.platform,
                Comment.platform_id == c.root_platform_id,
                Comment.root_platform_id.is_(None),
            )
        )
    )
    if root is None:
        raise ApiError(404, "COMMENT_NOT_FOUND", "根评论不存在")
    ranked = (
        select(
            Comment.id.label("id"),
            (func.row_number().over(order_by=comment_order(sort)) - 1).label("offset"),
        )
        .where(Comment.content_id == c.content_id, Comment.root_platform_id.is_(None))
        .subquery()
    )
    offset = await session.scalar(select(ranked.c.offset).where(ranked.c.id == root.id))
    assert offset is not None
    return CommentLocate(content_id=c.content_id, root_comment_id=root.id, offset=offset)


@router.get("/locate", response_model=LocateOut, responses=_404)
async def locate(
    session: Annotated[AsyncSession, Depends(get_session)],
    content_id: int | None = None,
    comment_id: int | None = None,
    prefer_dataset_id: int | None = None,
) -> LocateOut:
    """`content_id` 与 `comment_id` 二选一，为跳转找数据集。"""
    if (content_id is None) == (comment_id is None):
        raise ApiError(400, "INVALID_REQUEST", "请提供一个内容 ID 或评论 ID")
    if comment_id is not None:
        c: Comment = await require(session, Comment, comment_id)
        content_id = c.content_id
    assert content_id is not None
    await require(session, Content, content_id)
    datasets = (
        await session.scalars(
            select(Dataset)
            .join(DatasetItem)
            .where(DatasetItem.content_id == content_id)
            .order_by(Dataset.last_appended_at.desc().nulls_last(), Dataset.id.desc())
        )
    ).all()
    chosen = next(
        (d.id for d in datasets if d.id == prefer_dataset_id), datasets[0].id if datasets else None
    )
    return LocateOut(dataset_id=chosen, content_id=content_id, comment_id=comment_id)
