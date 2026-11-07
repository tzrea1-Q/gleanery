"""查询类工具。

工具描述于 2026-11-02 经 M2 真模型冒烟定稿。
"""

from typing import Any, Literal

from pydantic_ai import RunContext

from gleanery.agent.deps import AgentDeps
from gleanery.collect.plan import StringList
from gleanery.query import agent as queries
from gleanery.query.filters import ContentFilter, ContentSort
from gleanery.query.sql import SqlFailed, SqlRejected, SqlTimeout

CommentSort = Literal["likes", "time"]
GroupBy = Literal["platform", "author", "published_day", "published_week", "completeness"]
Metric = Literal["likes", "plays", "comments", "favorites", "shares"]
MentionScope = Literal["contents", "comments", "both"]


async def query_contents(
    ctx: RunContext[AgentDeps],
    dataset_id: int,
    filter: ContentFilter | None = None,
    sort: ContentSort = "likes_desc",
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """列出数据集里的内容，可筛选、排序、翻页。正文只给前 200 字，全文用 get_content。

    Args:
        dataset_id: 数据集 ID，不知道时先用 list_datasets。
        filter: 筛选条件，不需要时省略。
        sort: 排序，默认按点赞从高到低。
        limit: 每页条数，1 到 50。
        offset: 从第几条开始，翻页时用上次结果里的 next_offset。
    """
    async with ctx.deps.sessionmaker() as session:
        return await queries.query_contents(
            session, ctx.deps.tz, dataset_id, filter, sort, limit, offset
        )


async def get_content(
    ctx: RunContext[AgentDeps],
    content_id: int,
    comment_limit: int = 50,
    comment_sort: CommentSort = "likes",
    include_replies: bool = False,
    include_subtitles: bool = False,
    subtitle_max_chars: int = 4000,
) -> dict[str, Any]:
    """读一条内容的全文、一级评论（可带楼中楼回复）和字幕。

    Args:
        content_id: 内容 ID。
        comment_limit: 一级评论条数，0 到 200。
        comment_sort: likes 为按点赞，time 为最新在前。
        include_replies: 是否在每条一级评论下带回复（每楼最多 10 条）。
        include_subtitles: 是否带字幕全文。
        subtitle_max_chars: 每份字幕最多给多少字。
    """
    async with ctx.deps.sessionmaker() as session:
        return await queries.get_content(
            session,
            ctx.deps.tz,
            content_id,
            comment_limit,
            comment_sort,
            include_replies,
            include_subtitles,
            subtitle_max_chars,
        )


async def query_comments(
    ctx: RunContext[AgentDeps],
    dataset_id: int | None = None,
    content_id: int | None = None,
    keyword: str | None = None,
    min_likes: int | None = None,
    include_replies: bool = True,
    sort: CommentSort = "likes",
    limit: int = 30,
    offset: int = 0,
) -> dict[str, Any]:
    """查评论：给 dataset_id 查整个数据集的评论，或给 content_id 查一条内容的评论，二选一。
    评论正文只给前 300 字。

    Args:
        dataset_id: 数据集 ID。
        content_id: 内容 ID。
        keyword: 评论包含的词，子串匹配。
        min_likes: 点赞下限。
        include_replies: 是否包含楼中楼回复。
        sort: likes 为按点赞，time 为最新在前。
        limit: 每页条数，1 到 100。
        offset: 从第几条开始。
    """
    async with ctx.deps.sessionmaker() as session:
        return await queries.query_comments(
            session,
            ctx.deps.tz,
            dataset_id,
            content_id,
            keyword,
            min_likes,
            include_replies,
            sort,
            limit,
            offset,
        )


async def aggregate(
    ctx: RunContext[AgentDeps],
    dataset_id: int,
    group_by: GroupBy,
    metric: Metric | None = None,
    filter: ContentFilter | None = None,
) -> dict[str, Any]:
    """分组统计数据集里的内容：每组的条数，以及某个互动数的和、均值、中位数。

    Args:
        dataset_id: 数据集 ID。
        group_by: 按平台、作者、发布日、发布周（周一开始）或完整度分组。
        metric: 要统计的互动数；省略时只计条数。
        filter: 先筛选再统计。
    """
    async with ctx.deps.sessionmaker() as session:
        return await queries.aggregate(session, ctx.deps.tz, dataset_id, group_by, metric, filter)


async def count_mentions(
    ctx: RunContext[AgentDeps],
    dataset_id: int,
    terms: StringList,
    scope: MentionScope = "both",
    filter: ContentFilter | None = None,
) -> dict[str, Any]:
    """数一组主题词各被多少条内容、多少条评论提到，以及这些条目的点赞之和。
    用来给"大家最常说什么"这类问题给出数量。

    Args:
        dataset_id: 数据集 ID。
        terms: 1 到 30 个主题词；同一主题的同义词用 | 连起来，如 "续航|电池|充电"，命中任一即算。
        scope: contents 只数内容的标题和正文，comments 只数评论（含回复），both 两者都数。
        filter: 先筛选内容，评论随所属内容一起筛。
    """
    async with ctx.deps.sessionmaker() as session:
        return await queries.count_mentions(session, ctx.deps.tz, dataset_id, terms, scope, filter)


async def run_sql(ctx: RunContext[AgentDeps], sql: str) -> dict[str, Any]:
    """只读 SQL，结构化工具答不了时再用。只能查下列视图，最多返回 200 行，长文本截断到 500 字。

    - v_contents：content_id, platform, url, kind, title, body, author_id, author, published_at（UTC 毫秒）,
      published_local（本地时间文本）, likes, favorites, comments, shares, plays, coins, danmaku,
      duration_seconds, category, counts_approx, tags, completeness, local_comments, local_subtitles
    - v_comments：comment_id, content_id, root_comment_id, parent_comment_id, is_reply, author_id, author,
      body, published_at, published_local, likes, reply_count, ip_location
    - v_subtitles：subtitle_id, content_id, part_title, lang, ai_generated, chars, text
    - v_datasets：dataset_id, name, description, created_at, last_appended_at, content_count
    - v_dataset_items：dataset_id, content_id, added_at（限定某个数据集时 join 它）

    Args:
        sql: 一条 SELECT 语句（可以用 WITH，但 CTE 名不能以 v_ 开头）。
    """
    try:
        result = await ctx.deps.sql.run(sql)
    except SqlRejected:
        return queries.error("SQL_NOT_ALLOWED", "SQL 操作不允许")
    except SqlTimeout:
        return queries.error("SQL_TIMEOUT", "SQL 执行超时")
    except SqlFailed as exc:
        return queries.error("SQL_ERROR", "SQL 执行失败", str(exc))
    response = {
        "columns": result.columns,
        "returned": len(result.rows),
        "truncated": result.truncated,
        "untrusted": {"rows": result.rows},
    }
    if result.truncated or any(
        isinstance(v, str) and len(v) == 501 and v.endswith("…") for row in result.rows for v in row
    ):
        response["hint"] = "结果已截断，可用 get_content 取全文"
    return response
