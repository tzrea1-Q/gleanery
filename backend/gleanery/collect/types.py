"""任务状态、平台状态、限速参数。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from gleanery.platforms.types import Platform

TaskStatus = Literal["queued", "running", "paused", "completed", "stopped", "failed"]
"""排队中 / 执行中 / 已暂停 / 已完成 / 已停止 / 失败。前三个是非终态。"""

TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset({"completed", "stopped", "failed"})

PauseReason = Literal["risk", "login_lost", "user", "browser_disconnected", "app_restart"]
"""风控 / 登录失效 / 用户暂停 / 浏览器断开 / 应用重启（界面显示为"已中断"）。"""

FailReason = Literal["page_changed", "network"]

WaitReason = Literal[
    "queue",  # 前面还有任务
    "cooldown",  # 冷却中，到时自动开始
    "locked",  # 已锁定，等用户解锁
    "login_required",  # 需要登录，等用户扫码
    "quota_exhausted",  # 今日额度用尽，零点后自动开始
    "page_changed",  # 页面改版待确认，等用户决定
    "min_interval",  # 两次任务的最小间隔
    "warmup",  # 登录后预热
    "blocked_by_risk_pause",  # 本平台有风控暂停的任务等用户选择
]
"""排队任务的等待原因，按需计算，不落库。"""

PlatformStateName = Literal[
    "normal", "cooldown", "locked", "login_required", "quota_exhausted", "page_changed"
]


class RateLimits(BaseModel):
    """一个平台的限速与上限参数。间隔单位为秒。"""

    page_interval: tuple[float, float]
    """页面或详情请求间隔，随机取值范围。"""
    comment_page_interval: tuple[float, float]
    long_rest_every: int
    """每采这么多条内容长休息一次。"""
    long_rest: tuple[float, float]
    task_default_limit: int
    task_hard_cap: int
    """单任务内容数硬上限，不可调。"""
    daily_quota: int
    min_task_gap_minutes: float
    """两次任务的最小间隔。"""
    risk_cooldown_minutes: float
    lock_hours: float | None
    """24 小时内第二次风控的锁定时长；None 表示须手动解锁（小红书）。"""
    page_interval_floor: float
    """放宽时间隔下限（默认值下界的一半）。"""


DEFAULT_RATE_LIMITS: dict[Platform, RateLimits] = {
    "bili": RateLimits(
        page_interval=(3, 8),
        comment_page_interval=(2, 5),
        long_rest_every=50,
        long_rest=(60, 180),
        task_default_limit=100,
        task_hard_cap=300,
        daily_quota=1000,
        min_task_gap_minutes=10,
        risk_cooldown_minutes=30,
        lock_hours=6,
        page_interval_floor=1.5,
    ),
    "xhs": RateLimits(
        page_interval=(6, 15),
        comment_page_interval=(3, 6),
        long_rest_every=20,
        long_rest=(120, 300),
        task_default_limit=50,
        task_hard_cap=200,
        daily_quota=300,
        min_task_gap_minutes=30,
        risk_cooldown_minutes=120,
        lock_hours=None,
        page_interval_floor=3,
    ),
}

NETWORK_RETRY_DELAYS = (5.0, 15.0)
WARMUP_MINUTES_DEFAULT = 3
PAGE_CHANGE_MISSING_CORE_RATIO = 0.2
PAGE_CHANGE_MISSED_RESPONSES = 3


class TaskSnapshot(BaseModel):
    """确认时的计划快照；计划被删后任务靠它自描述。"""

    plan_title: str
    dataset_id: int
    dataset_name: str
    section: dict
    """本平台分段，`gleanery.collect.plan.PlatformSection` 的 JSON。"""
    follow_up: str | None = None
    confirmed_at: int
    rate_limits: RateLimits


Phase = Literal["waiting", "search", "content", "done"]


class TaskProgress(BaseModel):
    phase: Phase = "waiting"
    keyword: str | None = None
    discovered: int = 0
    """已发现的内容数（含指定内容）。"""
    planned: int = 0
    """计划要处理的内容数，即"实得 / 计划"里的计划。"""
    processed: int = 0
    comments: int = 0
    subtitles: int = 0
    quota_counted: int = 0
    """计入每日额度的条数。"""
    eta_seconds: int | None = None
    last_log: str | None = None
    parse_stats: dict[str, int] = Field(default_factory=dict)
    """次要字段缺失计数，任务摘要写成"有 N 条某字段缺失"。"""
    skipped_missing_core: int = 0
