"""M2 的 REST 模型：浏览与定位、数据集管理与删除、导出、数据设置。"""

from typing import Literal

from pydantic import BaseModel, Field

from gleanery.platforms.types import Completeness, Platform

# ---------- 浏览与定位 ----------


class LocateOffset(BaseModel):
    offset: int | None
    """在当前筛选与排序下的行号（从 0 起）；不在数据集里或被筛掉时为 None。"""


class DatasetRef(BaseModel):
    id: int
    name: str


class SubtitleOut(BaseModel):
    id: int
    part_id: str
    part_title: str | None
    lang: str
    ai_generated: bool
    chars: int
    text: str


class ContentDetail(BaseModel):
    id: int
    platform: Platform
    url: str
    kind: str
    title: str | None
    body: str | None
    author_id: int | None
    author_nickname: str | None
    published_at: int | None
    platform_updated_at: int | None
    likes: int | None
    favorites: int | None
    comments: int | None
    shares: int | None
    plays: int | None
    coins: int | None
    danmaku: int | None
    duration_seconds: int | None
    category: str | None
    counts_approx: bool
    tags: list[str]
    completeness: Completeness
    local_comments: int
    """本地已采的评论条数，含回复。"""
    subtitles: list[SubtitleOut]
    datasets: list[DatasetRef]
    """包含它的数据集，按最近追加倒序。"""


class CommentOut(BaseModel):
    id: int
    content_id: int
    root_comment_id: int | None
    parent_comment_id: int | None
    author_nickname: str | None
    body: str
    published_at: int | None
    likes: int | None
    reply_count: int | None
    ip_location: str | None
    replies: list["CommentOut"] = Field(default_factory=list)
    """一级评论下本地已有的全部回复，按时间正序；回复本身为空列表。"""


class CommentPage(BaseModel):
    total: int
    """本地一级评论数。"""
    replies_total: int
    items: list[CommentOut]


class CommentLocate(BaseModel):
    content_id: int
    root_comment_id: int
    """评论本身是一级评论时等于它自己。"""
    offset: int
    """根评论在一级评论里的行号（从 0 起）。"""


class LocateOut(BaseModel):
    dataset_id: int | None
    """优先 `prefer_dataset_id`，否则是包含它、最近追加的数据集；都没有时为 None。"""
    content_id: int
    comment_id: int | None


# ---------- 数据集管理与删除 ----------


class DatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None


class DeleteImpact(BaseModel):
    reports: int
    contents: int
    """数据集的成员条数。"""
    comments: int
    """成员内容的本地评论数，含回复。"""
    recycled_contents: int
    """删除后不再属于任何数据集、会被回收的内容条数。"""
    recycled_comments: int
    tasks: int
    """会一并删除的采集任务数。"""
    active_task_ids: list[int]
    """非终态（排队中、执行中、已暂停）的任务；不为空时须先停止。"""


class ContentIds(BaseModel):
    content_ids: list[int] = Field(min_length=1, max_length=500)


class RemoveImpact(BaseModel):
    removed: int
    not_member: list[int]
    """请求里不在该数据集中的内容 ID。"""
    recycled_contents: int
    recycled_comments: int


class DataImpact(BaseModel):
    datasets: int
    contents: int
    comments: int
    tasks: int
    raw_captures: int
    active_task_ids: list[int]


class ClearRequest(BaseModel):
    stop_active: bool = False
    """为真时先停止非终态任务再删除。"""


# ---------- 导出 ----------

ExportFormat = Literal["xlsx", "csv", "md"]


class ExportOptions(BaseModel):
    include_ext: bool = False
    """Excel、CSV：加扩展字段列。"""
    comment_limit: int = Field(default=20, ge=0, le=200)
    """Markdown：每条内容按点赞取前 N 条一级评论。"""
    include_subtitles: bool = False
    """Markdown：放字幕全文。"""


# ---------- 数据设置 ----------

RetentionDays = Literal[7, 30, 90]


class DataSettings(BaseModel):
    raw_retention_days: RetentionDays | None
    """None 为永久保留。"""
    raw_count: int
    raw_bytes: int
    db_bytes: int
    """库文件、WAL、SHM 之和。"""


class DataSettingsUpdate(BaseModel):
    raw_retention_days: RetentionDays | None


class PurgeResult(BaseModel):
    deleted: int
