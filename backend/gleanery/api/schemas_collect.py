"""M1 的 REST 契约：计划、任务、平台、数据集、采集设置、风控事件。

前端类型经 openapi-typescript 从这里生成，改动后跑 `just gen-api`。时间一律是 UTC 毫秒时间戳。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from gleanery.collect.plan import PlanBody
from gleanery.collect.types import (
    PlatformStateName,
    RateLimits,
    TaskProgress,
    TaskStatus,
    WaitReason,
)
from gleanery.platforms.types import Platform

# ---------- 计划 ----------


class PlanIssue(BaseModel):
    code: str
    """错误：`HARD_CAP_EXCEEDED`、`UNRESOLVABLE_LINK`、`EMPTY_SECTION` 等；提示：`QUOTA_EXCEEDED`（不阻止确认，
    "超出部分明天继续"）、`PLATFORM_NOT_READY`（附平台状态与预计开始时间）。"""
    message: str
    platform: Platform | None = None
    severity: Literal["error", "warning"]


class PlanOut(BaseModel):
    id: int
    conversation_id: int | None
    status: Literal["draft", "confirmed"]
    version: int
    body: PlanBody
    issues: list[PlanIssue]
    estimate_seconds: dict[str, int]
    """按平台的预计耗时，由应用按经验值计算。"""
    task_ids: list[int]
    confirmed_at: int | None
    created_at: int
    updated_at: int


class PlanPatch(BaseModel):
    base_version: int
    body: PlanBody


# ---------- 任务 ----------


class TaskOut(BaseModel):
    id: int
    plan_id: int | None
    dataset_id: int
    platform: Platform
    status: TaskStatus
    reason: str | None
    """暂停原因（PauseReason）或失败原因（FailReason）。"""
    wait_reason: WaitReason | None
    """仅排队中的任务有。"""
    wait_until: int | None
    """等待原因带截止时间时（冷却、额度、最小间隔、预热）。"""
    queue_position: int | None
    snapshot: dict[str, Any]
    progress: TaskProgress
    created_at: int
    started_at: int | None
    finished_at: int | None


# ---------- 平台 ----------

LoginPhase = Literal["idle", "waiting_scan", "verifying", "succeeded", "failed", "timeout"]


class LoginStatus(BaseModel):
    phase: LoginPhase
    message: str | None = None
    browser: Literal["chrome", "edge", "chromium"] | None = None
    """用到 Playwright Chromium 时界面要明示：需要下载，且 webdriver=true。"""


class PlatformOut(BaseModel):
    platform: Platform
    state: PlatformStateName
    reason: str | None
    cooldown_until: int | None
    locked_until: int | None
    quota_used: int
    daily_quota: int
    warmup_until: int | None
    last_probe_at: int | None
    last_probe_ok: bool | None
    last_probe_detail: str | None
    queue_length: int
    login: LoginStatus
    browser_running: bool


# ---------- 数据集 ----------


class DatasetOut(BaseModel):
    id: int
    name: str
    description: str
    created_in_conversation_id: int | None
    counts: dict[str, int]
    """按平台的内容条数，实时计算。"""
    total: int
    created_at: int
    last_appended_at: int | None


class ContentRow(BaseModel):
    id: int
    platform: Platform
    url: str
    open_url: str
    """给用户点开的网址：小红书带上 xsec_token，其余平台同 `url`。"""
    kind: str
    title: str | None
    body_excerpt: str | None
    """正文前 120 字。"""
    author_nickname: str | None
    published_at: int | None
    likes: int | None
    comments: int | None
    plays: int | None
    counts_approx: bool
    completeness: Literal["summary", "detail"]
    local_comments: int
    """本地已采的评论条数。"""
    subtitles: int
    added_at: int


class ContentPage(BaseModel):
    total: int
    """数据集的全部成员条数。"""
    filtered_total: int
    """符合当前筛选的条数，翻页按它算。"""
    items: list[ContentRow]


# ---------- 采集设置与风控事件 ----------


class PlatformRateSettings(BaseModel):
    current: RateLimits
    defaults: RateLimits


class CollectSettings(BaseModel):
    warmup_enabled: bool
    platforms: dict[str, PlatformRateSettings]


class RateLimitsUpdate(BaseModel):
    """可调的字段。收紧不设限；放宽时间隔不能低于 `page_interval_floor`；硬上限不可调。"""

    page_interval: tuple[float, float] | None = None
    comment_page_interval: tuple[float, float] | None = None
    task_default_limit: int | None = Field(default=None, ge=1)
    daily_quota: int | None = Field(default=None, ge=1)
    risk_cooldown_minutes: float | None = Field(default=None, gt=0)
    min_task_gap_minutes: float | None = Field(default=None, ge=0)


class CollectSettingsUpdate(BaseModel):
    warmup_enabled: bool | None = None
    platforms: dict[str, RateLimitsUpdate] | None = None


class RiskEventOut(BaseModel):
    id: int
    at: int
    platform: Platform
    signal: str
    signal_type: str
    task_id: int | None
    collected_count: int
    rate_params: dict[str, Any]
    outcome: str
    outcome_until: int | None
