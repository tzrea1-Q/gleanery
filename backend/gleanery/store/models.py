from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Report(Base):
    __tablename__ = "report"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    markdown: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("dataset.id", ondelete="SET NULL"))
    created_in_conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation.id", ondelete="SET NULL")
    )
    basis: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)
    updated_by: Mapped[str] = mapped_column(Text)


class ReportRevision(Base):
    __tablename__ = "report_revision"
    __table_args__ = (
        Index("ix_report_revision_report_id_version", "report_id", "version", unique=True),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("report.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    markdown: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation.id", ondelete="SET NULL")
    )
    created_at: Mapped[int] = mapped_column(BigInteger)


class ReportCitation(Base):
    __tablename__ = "report_citation"
    __table_args__ = (
        Index(
            "ix_report_citation_report_id_kind_target_id",
            "report_id",
            "kind",
            "target_id",
            unique=True,
        ),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("report.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    target_id: Mapped[int] = mapped_column(Integer)
    content_id: Mapped[int] = mapped_column(Integer)
    platform: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    saved_at: Mapped[int] = mapped_column(BigInteger)


class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text, server_default=text("''"))
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)


class Message(Base):
    __tablename__ = "message"
    __table_args__ = (UniqueConstraint("conversation_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversation.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[Any] = mapped_column(JSON)
    model_name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(BigInteger)


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class ModelConfig(Base):
    __tablename__ = "model_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    preset: Mapped[str] = mapped_column(Text)
    base_url: Mapped[str] = mapped_column(Text)
    api_style: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    status_reason: Mapped[str | None] = mapped_column(Text)
    available_models: Mapped[list[str] | None] = mapped_column(JSON)
    model_labels: Mapped[dict[str, str] | None] = mapped_column(JSON)
    client_id: Mapped[str | None] = mapped_column(Text)
    models_fetched_at: Mapped[int | None] = mapped_column(BigInteger)
    favorites: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)


# ---------- M1：内容库（ADR-0004） ----------
# 平台取值见 gleanery.platforms.types.Platform。时间一律是 UTC 毫秒整数。


class Author(Base):
    __tablename__ = "author"
    __table_args__ = (UniqueConstraint("platform", "platform_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(Text)
    platform_id: Mapped[str] = mapped_column(Text)
    nickname: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    ext: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)


class Content(Base):
    __tablename__ = "content"
    __table_args__ = (UniqueConstraint("platform", "platform_id"), {"sqlite_autoincrement": True})

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(Text)
    platform_id: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    """`image_text`（图文）或 `video`。"""
    title: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("author.id", ondelete="SET NULL"))
    published_at: Mapped[int | None] = mapped_column(BigInteger)
    platform_updated_at: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    favorites: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    plays: Mapped[int | None] = mapped_column(BigInteger)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    completeness: Mapped[str] = mapped_column(Text)
    """`summary`（仅摘要）或 `detail`（已详情），只升不降。"""
    metrics_observed_at: Mapped[int | None] = mapped_column(BigInteger)
    first_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_task.id", ondelete="SET NULL")
    )
    last_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_task.id", ondelete="SET NULL")
    )
    ext: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)


class Comment(Base):
    __tablename__ = "comment"
    __table_args__ = (
        UniqueConstraint("platform", "platform_id"),
        Index("ix_comment_content_id", "content_id"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(Text)
    platform_id: Mapped[str] = mapped_column(Text)
    content_id: Mapped[int] = mapped_column(ForeignKey("content.id", ondelete="CASCADE"))
    root_platform_id: Mapped[str | None] = mapped_column(Text)
    """根评论的平台内 ID；一级评论为 None。用平台内 ID 是因为子评论可能先于根评论入库。"""
    parent_platform_id: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("author.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    published_at: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    reply_count: Mapped[int | None] = mapped_column(BigInteger)
    ip_location: Mapped[str | None] = mapped_column(Text)
    first_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_task.id", ondelete="SET NULL")
    )
    last_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_task.id", ondelete="SET NULL")
    )
    ext: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)


class Subtitle(Base):
    __tablename__ = "subtitle"
    __table_args__ = (UniqueConstraint("content_id", "part_id", "lang"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("content.id", ondelete="CASCADE"))
    part_id: Mapped[str] = mapped_column(Text)
    """B 站分 P 的 cid。"""
    part_title: Mapped[str | None] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(Text)
    ai_generated: Mapped[bool] = mapped_column(Boolean)
    text: Mapped[str] = mapped_column(Text)
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    """`[{from, to, content}]`，秒。"""
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)


class ContentMetricSnapshot(Base):
    __tablename__ = "content_metric_snapshot"
    __table_args__ = (Index("ix_content_metric_snapshot_content_id", "content_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("content.id", ondelete="CASCADE"))
    observed_at: Mapped[int] = mapped_column(BigInteger)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_task.id", ondelete="SET NULL")
    )
    likes: Mapped[int | None] = mapped_column(BigInteger)
    favorites: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    plays: Mapped[int | None] = mapped_column(BigInteger)


class RawCapture(Base):
    __tablename__ = "raw_capture"
    __table_args__ = (Index("ix_raw_capture_task_id", "task_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("collection_task.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    """接口路径尾部（如 `x/v2/reply/wbi/main`）或 SSR 片段名（如 `ssr:search`）。"""
    url_path: Mapped[str] = mapped_column(Text)
    captured_at: Mapped[int] = mapped_column(BigInteger)
    body_gz: Mapped[bytes] = mapped_column(LargeBinary)
    """gzip 压缩的 `Capture` JSON（含状态码、白名单响应头、查询串、正文）。"""


# ---------- M1：数据集、计划、任务、平台状态 ----------


class Dataset(Base):
    __tablename__ = "dataset"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default=text("''"))
    created_in_conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation.id", ondelete="SET NULL")
    )
    created_at: Mapped[int] = mapped_column(BigInteger)
    last_appended_at: Mapped[int | None] = mapped_column(BigInteger)


class DatasetItem(Base):
    __tablename__ = "dataset_item"
    __table_args__ = (Index("ix_dataset_item_content_id", "content_id"),)

    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("dataset.id", ondelete="CASCADE"), primary_key=True
    )
    content_id: Mapped[int] = mapped_column(
        ForeignKey("content.id", ondelete="CASCADE"), primary_key=True
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_task.id", ondelete="SET NULL")
    )
    added_at: Mapped[int] = mapped_column(BigInteger)


class CollectionPlan(Base):
    __tablename__ = "collection_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(Text)
    """`draft` 或 `confirmed`（ADR-0002）。"""
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[dict[str, Any]] = mapped_column(JSON)
    """`gleanery.collect.plan.PlanBody` 的 JSON。"""
    target_dataset_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)


class CollectionTask(Base):
    __tablename__ = "collection_task"
    __table_args__ = (
        Index("ix_collection_task_platform_status", "platform", "status"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_plan.id", ondelete="SET NULL")
    )
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset.id", ondelete="CASCADE"))
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation.id", ondelete="SET NULL")
    )
    platform: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    """见 `gleanery.collect.types.TaskStatus`。"""
    reason: Mapped[str | None] = mapped_column(Text)
    """暂停或失败的原因（`TaskReason`），其余状态为 None。"""
    queue_key: Mapped[int] = mapped_column(BigInteger)
    """同平台排队顺序，小的先执行。"回到队首"即设为比当前最小值还小。"""
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    """`TaskSnapshot` 的 JSON：计划标题、目标数据集、本平台分段、后续意图、确认时间、限速参数。"""
    progress: Mapped[dict[str, Any]] = mapped_column(JSON)
    """`TaskProgress` 的 JSON。"""
    trigger: Mapped[str] = mapped_column(Text, server_default=text("'conversation'"))
    schedule_rule_id: Mapped[int | None] = mapped_column(Integer)
    """定时监控的扩展点，MVP 恒为 None。"""
    created_at: Mapped[int] = mapped_column(BigInteger)
    started_at: Mapped[int | None] = mapped_column(BigInteger)
    finished_at: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)


class TaskItem(Base):
    """任务内每条内容的处理状态，用于以内容为单位续跑。"""

    __tablename__ = "task_item"
    __table_args__ = (UniqueConstraint("task_id", "platform_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("collection_task.id", ondelete="CASCADE"))
    platform_id: Mapped[str] = mapped_column(Text)
    content_id: Mapped[int | None] = mapped_column(ForeignKey("content.id", ondelete="SET NULL"))
    ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    """`ContentRef` 的 JSON，打开内容页用。"""
    source: Mapped[str] = mapped_column(Text)
    """`search:<关键词>` 或 `target`（指定内容）。"""
    seq: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(Text)
    """`pending` / `done` / `skipped`。"""
    skip_reason: Mapped[str | None] = mapped_column(Text)


class PlatformState(Base):
    __tablename__ = "platform_state"

    platform: Mapped[str] = mapped_column(Text, primary_key=True)
    state: Mapped[str] = mapped_column(Text)
    """见 `gleanery.collect.types.PlatformStateName`。"""
    reason: Mapped[str | None] = mapped_column(Text)
    cooldown_until: Mapped[int | None] = mapped_column(BigInteger)
    locked_until: Mapped[int | None] = mapped_column(BigInteger)
    """B 站锁定 6 小时后自动解除；小红书锁定为 None，须手动解锁。"""
    quota_day: Mapped[str | None] = mapped_column(Text)
    """本地日期 YYYY-MM-DD，跨日时清零 quota_used。"""
    quota_used: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    warmup_until: Mapped[int | None] = mapped_column(BigInteger)
    last_task_finished_at: Mapped[int | None] = mapped_column(BigInteger)
    last_probe_at: Mapped[int | None] = mapped_column(BigInteger)
    last_probe_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_probe_detail: Mapped[str | None] = mapped_column(Text)
    last_visit_at: Mapped[int | None] = mapped_column(BigInteger)
    """最近一次打开平台页面的时间；空闲超过 3 天时任务前先开首页。"""
    page_change_build: Mapped[str | None] = mapped_column(Text)
    """判为页面改版时的应用版本；应用升级后自动清除"页面改版待确认"。"""
    updated_at: Mapped[int] = mapped_column(BigInteger)


class RiskEvent(Base):
    __tablename__ = "risk_event"
    __table_args__ = (Index("ix_risk_event_platform_at", "platform", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[int] = mapped_column(BigInteger)
    platform: Mapped[str] = mapped_column(Text)
    signal: Mapped[str] = mapped_column(Text)
    """如 `http_412`、`code_-352`、`v_voucher`、`login_lost`。"""
    signal_type: Mapped[str] = mapped_column(Text)
    """`status` / `code` / `login_lost` / `page`（跳验证页等）。"""
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_task.id", ondelete="SET NULL")
    )
    collected_count: Mapped[int] = mapped_column(Integer)
    rate_params: Mapped[dict[str, Any]] = mapped_column(JSON)
    outcome: Mapped[str] = mapped_column(Text)
    """`cooldown` / `locked` / `login_required`。"""
    outcome_until: Mapped[int | None] = mapped_column(BigInteger)
