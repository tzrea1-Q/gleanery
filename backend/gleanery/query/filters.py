"""查询工具、浏览接口、导出共用的筛选与排序。"""

from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, exists, nulls_last, or_, select
from sqlalchemy.orm import InstrumentedAttribute

from gleanery.platforms.types import Completeness, Platform
from gleanery.store.models import Author, Content, Subtitle

ContentSort = Literal[
    "added_desc", "published_desc", "published_asc", "likes_desc", "plays_desc", "comments_desc"
]


class ContentFilter(BaseModel):
    platform: Platform | None = None
    keyword: str | None = Field(default=None, description="标题或正文包含的词，子串匹配")
    author: str | None = Field(default=None, description="作者昵称包含的词")
    published_from: date | None = Field(default=None, description="发布日期下限，本地日期，含当天")
    published_to: date | None = Field(default=None, description="发布日期上限，本地日期，含当天")
    min_likes: int | None = Field(default=None, ge=0)
    min_plays: int | None = Field(default=None, ge=0)
    min_comments: int | None = Field(default=None, ge=0, description="平台上的评论数下限")
    completeness: Completeness | None = Field(
        default=None, description="summary 为仅摘要，detail 为已详情"
    )
    has_subtitles: bool | None = None

    def is_empty(self) -> bool:
        return not self.model_dump(exclude_none=True)


def like_pattern(word: str) -> str:
    """`LIKE ... ESCAPE '\\'` 用的子串模式。"""
    escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def like(column: InstrumentedAttribute[str | None], word: str) -> ColumnElement[bool]:
    return column.like(like_pattern(word), escape="\\")


def day_start_ms(day: date, tz: tzinfo | None) -> int:
    start = datetime.combine(day, time.min)
    start = start.replace(tzinfo=tz) if tz is not None else start.astimezone()
    return int(start.timestamp() * 1000)


def content_conditions(
    filter: ContentFilter | None, tz: tzinfo | None
) -> list[ColumnElement[bool]]:
    """作用在 `Content` 上的条件；调用方自己 join `DatasetItem` 限定数据集。"""
    if filter is None:
        return []
    conditions: list[ColumnElement[bool]] = []
    if filter.platform is not None:
        conditions.append(Content.platform == filter.platform)
    if filter.keyword:
        conditions.append(
            or_(like(Content.title, filter.keyword), like(Content.body, filter.keyword))
        )
    if filter.author:
        conditions.append(
            exists(
                select(Author.id).where(
                    Author.id == Content.author_id, like(Author.nickname, filter.author)
                )
            )
        )
    if filter.published_from is not None:
        conditions.append(Content.published_at >= day_start_ms(filter.published_from, tz))
    if filter.published_to is not None:
        end = day_start_ms(filter.published_to + timedelta(days=1), tz)
        conditions.append(Content.published_at < end)
    for column, bound in (
        (Content.likes, filter.min_likes),
        (Content.plays, filter.min_plays),
        (Content.comments, filter.min_comments),
    ):
        if bound is not None:
            conditions.append(column >= bound)
    if filter.completeness is not None:
        conditions.append(Content.completeness == filter.completeness)
    if filter.has_subtitles is not None:
        has = exists(select(Subtitle.id).where(Subtitle.content_id == Content.id))
        conditions.append(has if filter.has_subtitles else ~has)
    return conditions


def content_order(sort: ContentSort, added_at: InstrumentedAttribute[int]) -> list[Any]:
    """排序为 NULL 的值排在最后，同值按内容 ID 倒序，翻页稳定。`added_at` 传 `DatasetItem.added_at`。"""
    column, descending = {
        "added_desc": (added_at, True),
        "published_desc": (Content.published_at, True),
        "published_asc": (Content.published_at, False),
        "likes_desc": (Content.likes, True),
        "plays_desc": (Content.plays, True),
        "comments_desc": (Content.comments, True),
    }[sort]
    return [nulls_last(column.desc() if descending else column.asc()), Content.id.desc()]
