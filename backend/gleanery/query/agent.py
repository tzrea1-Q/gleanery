"""查询工具使用的内容库查询。"""

from collections import defaultdict
from datetime import timedelta
from statistics import median
from string import ascii_lowercase, ascii_uppercase
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.query.filters import ContentSort, content_conditions, content_order, like
from gleanery.query.timefmt import local_datetime, local_iso
from gleanery.store.models import Author, Comment, Content, Dataset, DatasetItem, Subtitle


def error(code: str, message: str, hint: str = "") -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "hint": hint}}


def excerpt(text: str | None, limit: int) -> tuple[str | None, bool]:
    if text is not None and len(text) > limit:
        return text[:limit] + "…", True
    return text, False


def page(items: list[Any], total: int, offset: int) -> dict[str, Any]:
    end = offset + len(items)
    return {
        "total": total,
        "offset": offset,
        "returned": len(items),
        "next_offset": end if end < total else None,
        "items": items,
    }


async def content_item(
    session: AsyncSession, c: Content, tz: Any, full: bool = False
) -> dict[str, Any]:
    author = await session.get(Author, c.author_id) if c.author_id is not None else None
    comments = await session.scalar(
        select(func.count()).select_from(Comment).where(Comment.content_id == c.id)
    )
    subtitles = await session.scalar(
        select(func.count()).select_from(Subtitle).where(Subtitle.content_id == c.id)
    )
    body, truncated = (c.body, False) if full else excerpt(c.body, 200)
    item = {
        "content_id": c.id,
        "platform": c.platform,
        "url": c.url,
        "kind": c.kind,
        "published_at": local_iso(c.published_at, tz),
        "likes": c.likes,
        "favorites": c.favorites,
        "comments": c.comments,
        "shares": c.shares,
        "plays": c.plays,
        "counts_approx": bool(c.ext.get("counts_approx", False)),
        "completeness": c.completeness,
        "local_comments": comments,
        "subtitles": subtitles,
        "untrusted": {
            "title": c.title,
            "body" if full else "body_excerpt": body,
            "author": author.nickname if author else None,
        },
    }
    if truncated:
        item["truncated"] = True
    return item


async def comment_item(
    session: AsyncSession, c: Comment, tz: Any, full: bool = False
) -> dict[str, Any]:
    author = await session.get(Author, c.author_id) if c.author_id is not None else None
    body, truncated = excerpt(c.body, 300)
    item = {
        "comment_id": c.id,
        "likes": c.likes,
        "reply_count": c.reply_count,
        "published_at": local_iso(c.published_at, tz),
        "untrusted": {"body": body, "author": author.nickname if author else None},
    }
    if full:
        item["untrusted"]["ip_location"] = c.ip_location
    if truncated:
        item["truncated"] = True
    return item


def comment_order(sort: str) -> list[Any]:
    col = Comment.likes if sort == "likes" else Comment.published_at
    return [col.desc().nulls_last(), Comment.id.desc()]


async def query_contents(
    session: AsyncSession,
    tz: Any,
    dataset_id: int,
    filter: Any,
    sort: ContentSort,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    if not 1 <= limit <= 50 or offset < 0:
        return error("INVALID_REQUEST", "分页参数无效")
    if not await session.get(Dataset, dataset_id):
        return error("DATASET_NOT_FOUND", "数据集不存在")
    query = (
        select(Content)
        .join(DatasetItem, DatasetItem.content_id == Content.id)
        .where(DatasetItem.dataset_id == dataset_id, *content_conditions(filter, tz))
    )
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    contents = (
        await session.scalars(
            query.order_by(*content_order(sort, DatasetItem.added_at)).limit(limit).offset(offset)
        )
    ).all()
    items = [await content_item(session, c, tz) for c in contents]
    result = {"dataset_id": dataset_id, **page(items, total, offset)}
    if any(i.get("truncated") for i in items):
        result["hint"] = "文本已截断，可用 get_content 取全文"
    return result


async def get_content(
    session: AsyncSession,
    tz: Any,
    content_id: int,
    comment_limit: int,
    comment_sort: str,
    include_replies: bool,
    include_subtitles: bool,
    subtitle_max_chars: int,
) -> dict[str, Any]:
    if (
        not 0 <= comment_limit <= 200
        or subtitle_max_chars < 0
        or comment_sort not in ("likes", "time")
    ):
        return error("INVALID_REQUEST", "参数无效")
    c = await session.get(Content, content_id)
    if c is None:
        return error("CONTENT_NOT_FOUND", "内容不存在")
    result = await content_item(session, c, tz, True)
    result["untrusted"]["tags"] = c.tags
    result.update(
        coins=c.ext.get("coins"),
        danmaku=c.ext.get("danmaku"),
        duration_seconds=c.ext.get("duration"),
    )
    datasets = (
        await session.scalars(
            select(Dataset).join(DatasetItem).where(DatasetItem.content_id == c.id)
        )
    ).all()
    result["datasets"] = [{"dataset_id": d.id, "name": d.name} for d in datasets]
    all_comments = (await session.scalars(select(Comment).where(Comment.content_id == c.id))).all()
    roots = (
        await session.scalars(
            select(Comment)
            .where(Comment.content_id == c.id, Comment.root_platform_id.is_(None))
            .order_by(*comment_order(comment_sort))
            .limit(comment_limit)
        )
    ).all()
    result["comments_total"] = sum(x.root_platform_id is None for x in all_comments)
    result["replies_total"] = sum(x.root_platform_id is not None for x in all_comments)
    comments = []
    for root in roots:
        item = await comment_item(session, root, tz, True)
        if include_replies:
            replies = sorted(
                (x for x in all_comments if x.root_platform_id == root.platform_id),
                key=lambda x: (x.published_at is None, x.published_at or 0, x.id),
            )[:10]
            item["replies"] = [await comment_item(session, x, tz, True) for x in replies]
        comments.append(item)
    result["comments"] = comments
    result["subtitles"] = []
    if include_subtitles:
        for sub in (
            await session.scalars(select(Subtitle).where(Subtitle.content_id == c.id))
        ).all():
            text, truncated = excerpt(sub.text, subtitle_max_chars)
            result["subtitles"].append(
                {
                    "subtitle_id": sub.id,
                    "lang": sub.lang,
                    "ai_generated": sub.ai_generated,
                    "chars": len(sub.text),
                    "truncated": truncated,
                    "untrusted": {"part_title": sub.part_title, "text": text},
                }
            )
    if any(
        i.get("truncated") or any(r.get("truncated") for r in i.get("replies", []))
        for i in comments
    ) or any(s["truncated"] for s in result["subtitles"]):
        result["hint"] = "文本已截断，可用 get_content 取全文"
    return result


async def query_comments(
    session: AsyncSession,
    tz: Any,
    dataset_id: int | None,
    content_id: int | None,
    keyword: str | None,
    min_likes: int | None,
    include_replies: bool,
    sort: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    if (
        (dataset_id is None) == (content_id is None)
        or not 1 <= limit <= 100
        or offset < 0
        or sort not in ("likes", "time")
        or (min_likes is not None and min_likes < 0)
    ):
        return error("INVALID_REQUEST", "查询参数无效")
    if dataset_id is not None and not await session.get(Dataset, dataset_id):
        return error("DATASET_NOT_FOUND", "数据集不存在")
    if content_id is not None and not await session.get(Content, content_id):
        return error("CONTENT_NOT_FOUND", "内容不存在")
    query = select(Comment).join(Content, Comment.content_id == Content.id)
    if dataset_id is not None:
        query = query.join(DatasetItem, DatasetItem.content_id == Content.id).where(
            DatasetItem.dataset_id == dataset_id
        )
    else:
        query = query.where(Comment.content_id == content_id)
    if keyword:
        query = query.where(like(Comment.body, keyword))
    if min_likes is not None:
        query = query.where(Comment.likes >= min_likes)
    if not include_replies:
        query = query.where(Comment.root_platform_id.is_(None))
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await session.scalars(query.order_by(*comment_order(sort)).limit(limit).offset(offset))
    ).all()
    items = []
    for c in rows:
        content = await session.get(Content, c.content_id)
        assert content is not None
        item = await comment_item(session, c, tz)
        item.update(
            content_id=c.content_id, url=content.url, is_reply=c.root_platform_id is not None
        )
        item["untrusted"]["content_title"] = content.title
        items.append(item)
    result = page(items, total, offset)
    if any(i.get("truncated") for i in items):
        result["hint"] = "文本已截断，可用 get_content 取全文"
    return result


async def dataset_contents(
    session: AsyncSession, tz: Any, dataset_id: int, filter: Any
) -> list[Content]:
    return list(
        (
            await session.scalars(
                select(Content)
                .join(DatasetItem, DatasetItem.content_id == Content.id)
                .where(DatasetItem.dataset_id == dataset_id, *content_conditions(filter, tz))
            )
        ).all()
    )


def stats(contents: list[Content], metric: str | None) -> dict[str, Any]:
    values = [getattr(c, metric) for c in contents if metric and getattr(c, metric) is not None]
    return {
        "count": len(contents),
        "metric_count": len(values),
        "sum": sum(values) if values else None,
        "avg": round(sum(values) / len(values), 2) if values else None,
        "median": median(values) if values else None,
    }


async def aggregate(
    session: AsyncSession, tz: Any, dataset_id: int, group_by: str, metric: str | None, filter: Any
) -> dict[str, Any]:
    if group_by not in (
        "platform",
        "author",
        "published_day",
        "published_week",
        "completeness",
    ) or metric not in (None, "likes", "plays", "comments", "favorites", "shares"):
        return error("INVALID_REQUEST", "分组或指标无效")
    if not await session.get(Dataset, dataset_id):
        return error("DATASET_NOT_FOUND", "数据集不存在")
    # 全量分组受内存限制；数据集变大时改为分批统计。
    contents = await dataset_contents(session, tz, dataset_id, filter)
    groups: dict[Any, list[Content]] = defaultdict(list)
    for c in contents:
        if group_by == "author":
            key = c.author_id
        elif group_by.startswith("published_"):
            day = local_datetime(c.published_at, tz).date() if c.published_at is not None else None
            key = (
                (
                    day - timedelta(days=day.weekday()) if group_by == "published_week" else day
                ).isoformat()
                if day
                else None
            )
        else:
            key = getattr(c, group_by)
        groups[key].append(c)
    ordered = (
        sorted(groups, key=lambda k: (k is None, k or ""))
        if group_by.startswith("published_")
        else sorted(groups, key=lambda k: -len(groups[k]))
    )
    result_groups = []
    for key in ordered[:200]:
        item = {"key": key, **stats(groups[key], metric)}
        if group_by == "author":
            author = await session.get(Author, key) if key is not None else None
            item["untrusted"] = {"author": author.nickname if author else None}
        result_groups.append(item)
    return {
        "groups": result_groups,
        "overall": stats(contents, metric),
        "truncated": len(ordered) > 200,
    }


async def count_mentions(
    session: AsyncSession, tz: Any, dataset_id: int, terms: list[str], scope: str, filter: Any
) -> dict[str, Any]:
    if (
        not 1 <= len(terms) <= 30
        or any(not t or any(not part.strip() for part in t.split("|")) for t in terms)
        or scope not in ("contents", "comments", "both")
    ):
        return error("INVALID_REQUEST", "词语或范围无效")
    if not await session.get(Dataset, dataset_id):
        return error("DATASET_NOT_FOUND", "数据集不存在")
    # 全量匹配受内存限制；数据集变大时改为分批查询。
    contents = await dataset_contents(session, tz, dataset_id, filter)
    ids = [c.id for c in contents]
    comments = list(
        (await session.scalars(select(Comment).where(Comment.content_id.in_(ids)))).all()
    )
    items = []
    ascii_fold = str.maketrans(ascii_uppercase, ascii_lowercase)
    for term in terms:
        words = [w.strip().translate(ascii_fold) for w in term.split("|")]
        matches_c = [
            c
            for c in contents
            if any(
                w in text.translate(ascii_fold)
                for w in words
                for text in (c.title or "", c.body or "")
            )
        ]
        matches_m = [c for c in comments if any(w in c.body.translate(ascii_fold) for w in words)]
        items.append(
            {
                "term": term,
                "contents": len(matches_c) if scope != "comments" else None,
                "contents_likes": sum(c.likes or 0 for c in matches_c)
                if scope != "comments"
                else None,
                "comments": len(matches_m) if scope != "contents" else None,
                "comments_likes": sum(c.likes or 0 for c in matches_m)
                if scope != "contents"
                else None,
            }
        )
    return {"contents_total": len(contents), "comments_total": len(comments), "items": items}
