from __future__ import annotations

from datetime import datetime, time, timedelta, tzinfo
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.collect.settings import load_rate_limits
from gleanery.collect.types import PlatformStateName, WaitReason
from gleanery.events import EventBus
from gleanery.platforms.types import Platform, RiskVerdict
from gleanery.store.models import CollectionTask, PlatformState, RiskEvent


def day_and_midnight(now: int, tz: tzinfo | None) -> tuple[str, int]:
    current = datetime.fromtimestamp(now / 1000, tz)
    tomorrow = datetime.combine(current.date() + timedelta(days=1), time.min, tzinfo=tz)
    return current.date().isoformat(), int(tomorrow.timestamp() * 1000)


async def get_state(session: AsyncSession, platform: Platform, now: int) -> PlatformState:
    state = await session.get(PlatformState, platform)
    if state is None:
        state = PlatformState(platform=platform, state="normal", quota_used=0, updated_at=now)
        session.add(state)
        await session.flush()
    return state


async def view(
    session: AsyncSession,
    platform: Platform,
    now: int,
    tz: tzinfo | None,
    events: EventBus | None,
) -> dict:
    """平台状态视图。冷却、锁定到期与换日在这里惰性恢复。

    `events` 为 None 时只读：恢复只改内存里的行，不发事件。读接口不提交会话，若照样发
    platform.updated，前端收到后重新拉取又会"恢复"一次，形成无限刷新（2026-11-01 e2e 发现）。
    真正落库并通知由 worker 的调度循环与执行器负责。
    """
    state = await get_state(session, platform, now)
    limits = await load_rate_limits(session, platform)
    day, midnight = day_and_midnight(now, tz)
    changed = False
    if state.quota_day != day:
        state.quota_day, state.quota_used = day, 0
        if state.state == "quota_exhausted":
            state.state = "normal"
        changed = True
    if (
        state.state == "cooldown"
        and state.cooldown_until is not None
        and state.cooldown_until <= now
    ):
        state.state = "login_required" if state.reason == "risk_and_login" else "normal"
        state.cooldown_until = None
        state.reason = None
        changed = True
    if state.state == "locked" and state.locked_until is not None and state.locked_until <= now:
        state.state = "login_required" if state.reason == "risk_and_login" else "normal"
        state.locked_until = None
        state.reason = None
        changed = True
    if changed and events is not None:
        state.updated_at = now
        await session.flush()
        events.publish("platform.updated", {"platform": platform})
        queued_tasks = await session.scalars(
            select(CollectionTask).where(
                CollectionTask.platform == platform, CollectionTask.status == "queued"
            )
        )
        for task in queued_tasks:
            events.publish("task.updated", {"task_id": task.id, "plan_id": task.plan_id})
    queued = int(
        await session.scalar(
            select(func.count())
            .select_from(CollectionTask)
            .where(CollectionTask.platform == platform, CollectionTask.status == "queued")
        )
        or 0
    )
    risk_paused = await session.scalar(
        select(CollectionTask.id)
        .where(
            CollectionTask.platform == platform,
            CollectionTask.status == "paused",
            CollectionTask.reason == "risk",
        )
        .limit(1)
    )
    reason: WaitReason | None = None
    until = None
    if state.state == "page_changed":
        reason = "page_changed"
    elif state.state == "locked":
        reason, until = "locked", state.locked_until
    elif state.state == "login_required" or state.reason == "risk_and_login":
        reason = "login_required"
    elif risk_paused is not None:
        reason = "blocked_by_risk_pause"
    elif state.state == "cooldown" and state.cooldown_until is not None:
        reason, until = "cooldown", state.cooldown_until
    elif state.quota_used >= limits.daily_quota:
        reason, until = "quota_exhausted", midnight
    elif state.warmup_until is not None and state.warmup_until > now:
        reason, until = "warmup", state.warmup_until
    elif (
        state.last_task_finished_at is not None
        and (gap_until := state.last_task_finished_at + int(limits.min_task_gap_minutes * 60000))
        > now
    ):
        reason, until = "min_interval", gap_until
    display_state = state.state
    if display_state == "normal" and state.quota_used >= limits.daily_quota:
        display_state = "quota_exhausted"
    return dict(
        platform=platform,
        state=cast(PlatformStateName, display_state),
        reason=state.reason,
        wait_reason=reason,
        wait_until=until,
        cooldown_until=state.cooldown_until,
        locked_until=state.locked_until,
        quota_used=state.quota_used,
        daily_quota=limits.daily_quota,
        warmup_until=state.warmup_until,
        last_probe_at=state.last_probe_at,
        last_probe_ok=state.last_probe_ok,
        last_probe_detail=state.last_probe_detail,
        queue_length=queued,
    )


async def record_risk(
    session: AsyncSession, platform: Platform, verdict: RiskVerdict, task_id: int | None, now: int
) -> None:
    state = await get_state(session, platform, now)
    task = await session.get(CollectionTask, task_id) if task_id is not None else None
    limits = await load_rate_limits(session, platform)
    if task is not None and task.started_at is not None:
        from gleanery.collect.types import TaskSnapshot

        limits = TaskSnapshot.model_validate(task.snapshot).rate_limits
    prior = await session.scalar(
        select(RiskEvent.id)
        .where(
            RiskEvent.platform == platform,
            RiskEvent.at >= now - 86400000,
            RiskEvent.at <= now,
            RiskEvent.outcome != "login_required",
        )
        .limit(1)
    )
    until = None
    if verdict.kind == "login_required":
        outcome = "login_required"
        state.state = "login_required"
        state.reason = verdict.signal
    elif prior is not None:
        outcome = "locked"
        until = now + int(limits.lock_hours * 3600000) if limits.lock_hours is not None else None
        state.state, state.locked_until = "locked", until
        state.reason = "risk_and_login" if verdict.kind == "risk_and_login" else verdict.signal
    else:
        outcome = "cooldown"
        until = now + int(limits.risk_cooldown_minutes * 60000)
        state.state, state.cooldown_until = "cooldown", until
        state.reason = "risk_and_login" if verdict.kind == "risk_and_login" else verdict.signal
    state.updated_at = now
    session.add(
        RiskEvent(
            at=now,
            platform=platform,
            signal=verdict.signal,
            signal_type=verdict.signal_type,
            task_id=task_id,
            collected_count=task.progress.get("processed", 0) if task else 0,
            rate_params=limits.model_dump(mode="json"),
            outcome=outcome,
            outcome_until=until,
        )
    )
