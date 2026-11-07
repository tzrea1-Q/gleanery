"""执行器对外的唯一入口。

REST、Agent 工具、登录编排都只经这里改任务与平台状态。改动队列或平台状态后都要
唤醒对应平台的 worker，并发 `task.updated` / `platform.updated`。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import tzinfo
from typing import cast

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gleanery.collect import platform_state
from gleanery.collect.plan import PlatformSection
from gleanery.collect.runtime import PlatformRuntime
from gleanery.collect.types import PlatformStateName, WaitReason
from gleanery.deps import Clock
from gleanery.events import EventBus
from gleanery.platforms.types import ContentRef, Platform, RiskVerdict
from gleanery.store.models import CollectionPlan, CollectionTask, Dataset, PlatformState


class PlatformView(BaseModel):
    """平台状态的读视图。冷却、锁定到期后已惰性恢复为正常。"""

    platform: Platform
    state: PlatformStateName
    reason: str | None
    wait_reason: WaitReason | None
    """平台级等待原因；为 None 时可以开始下一个任务。"""
    wait_until: int | None
    cooldown_until: int | None
    locked_until: int | None
    quota_used: int
    """今天（本地日期）已用额度。"""
    daily_quota: int
    warmup_until: int | None
    last_probe_at: int | None
    last_probe_ok: bool | None
    last_probe_detail: str | None
    queue_length: int
    """排队中的任务数（不含已暂停）。"""


class InvalidTransition(Exception):
    """非法的任务状态转移。REST 返回 409 `INVALID_TRANSITION`。"""


PlanFinishedHook = Callable[[int], Awaitable[None]]
"""一份计划的全部任务进入终态时调用，参数为 plan_id。由 C 波注册"采集结束"事件卡片。"""


class CollectService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        events: EventBus,
        clock: Clock,
        runtime: PlatformRuntime | None,
        *,
        app_version: str,
        tz: tzinfo | None = None,
    ) -> None:
        """`tz` 用于判定"今天"（每日额度），None 为本机时区。"""
        self.sessionmaker = sessionmaker
        self.events = events
        self.clock = clock
        self.runtime = runtime
        self.app_version = app_version
        self.tz = tz
        self.plan_finished_hooks: list[PlanFinishedHook] = []
        self._wake_events: dict[Platform, asyncio.Event] = {}
        self._workers: dict[Platform, asyncio.Task[None]] = {}
        self._active: dict[Platform, asyncio.Task[None]] = {}
        self._active_ids: dict[Platform, int] = {}
        self._locks: dict[Platform, asyncio.Lock] = {}
        self._notifications: set[asyncio.Task[None]] = set()
        self._started = False

    # ---------- 生命周期 ----------

    async def start(self) -> None:
        """执行中的任务标为已暂停（app_restart）；按版本清除页面改版状态；为有运行时的平台起 worker。"""
        now = self.clock.now_ms()
        async with self.sessionmaker.begin() as session:
            tasks = list(
                await session.scalars(
                    select(CollectionTask).where(CollectionTask.status == "running")
                )
            )
            states = list(
                await session.scalars(
                    select(PlatformState).where(PlatformState.state == "page_changed")
                )
            )
            changed_platforms = []
            for task in tasks:
                task.status = "paused"
                task.reason = "app_restart"
                task.updated_at = now
            for state in states:
                if state.page_change_build != self.app_version:
                    state.state = "login_required" if state.reason == "risk_and_login" else "normal"
                    state.reason = None
                    state.page_change_build = None
                    state.updated_at = now
                    changed_platforms.append(state.platform)
            if self.runtime is not None:
                for platform in self.runtime.platforms:
                    await platform_state.view(session, platform, now, self.tz, self.events)
            task_ids = [(task.id, task.plan_id) for task in tasks]
        for task_id, plan_id in task_ids:
            self.events.publish("task.updated", {"task_id": task_id, "plan_id": plan_id})
        for platform in changed_platforms:
            self.events.publish("platform.updated", {"platform": platform})
        self._started = True
        if self.runtime is not None:
            for platform in self.runtime.platforms:
                if platform not in self._workers:
                    self._wake_events[platform] = asyncio.Event()
                    self._workers[platform] = asyncio.create_task(worker.run(self, platform))

    async def stop(self) -> None:
        """取消 worker；执行中的任务按 app_restart 落库。"""
        tasks = list(self._workers.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._notifications:
            await asyncio.gather(*self._notifications, return_exceptions=True)
        self._workers.clear()
        self._wake_events.clear()
        self._started = False
        now = self.clock.now_ms()
        async with self.sessionmaker.begin() as session:
            running = list(
                await session.scalars(
                    select(CollectionTask).where(CollectionTask.status == "running")
                )
            )
            changed = [(task.id, task.plan_id) for task in running]
            for task in running:
                task.status, task.reason, task.updated_at = "paused", "app_restart", now
        for task_id, plan_id in changed:
            self._task_event(task_id, plan_id)

    def wake(self, platform: Platform) -> None:
        event = self._wake_events.get(platform)
        if event is not None:
            event.set()
        if self._started:
            task = asyncio.create_task(self._notify_queue(platform))
            self._notifications.add(task)
            task.add_done_callback(self._notifications.discard)

    async def _notify_queue(self, platform: Platform) -> None:
        async with self.sessionmaker() as session:
            tasks = list(
                await session.scalars(
                    select(CollectionTask).where(
                        CollectionTask.platform == platform, CollectionTask.status == "queued"
                    )
                )
            )
            for task in tasks:
                self._task_event(task.id, task.plan_id)

    # ---------- 入队与用户操作 ----------

    async def enqueue_plan(
        self,
        session: AsyncSession,
        plan: CollectionPlan,
        dataset: Dataset,
        sections: list[PlatformSection],
        resolved: dict[Platform, list[ContentRef]],
        now: int,
    ) -> list[int]:
        """每个平台分段建一个排队任务（快照、队尾、指定内容写成 task_item）。不 commit，
        调用方提交后再 `wake`。返回任务 ID，顺序同 `sections`。"""
        return await repo_tasks.enqueue(session, plan, dataset, sections, resolved, now)

    async def pause(self, task_id: int) -> TaskView:
        return await self._transition(task_id, "pause")

    async def resume(self, task_id: int) -> TaskView:
        """已暂停 → 回到本平台队首排队。"""
        return await self._transition(task_id, "resume")

    async def stop_tasks(
        self, *, task_id: int | None = None, plan_id: int | None = None
    ) -> list[TaskView]:
        """停止其中的非终态任务；已是终态的原样返回。"""
        if task_id is None and plan_id is None:
            raise ValueError("必须指定任务或计划")
        async with self.sessionmaker() as session:
            query = select(CollectionTask.id)
            if task_id is not None:
                query = query.where(CollectionTask.id == task_id)
            if plan_id is not None:
                query = query.where(CollectionTask.plan_id == plan_id)
            ids = list(await session.scalars(query))
        if task_id is not None and not ids:
            raise LookupError("任务不存在")
        return [await self._transition(identifier, "stop") for identifier in ids]

    # ---------- 平台操作（登录编排、探活、设置页） ----------

    async def on_login_succeeded(self, platform: Platform, warmup_minutes: float | None) -> None:
        """需要登录 → 正常；设预热截止时间；因登录失效暂停的任务回到队首。"""
        now = self.clock.now_ms()
        async with self.sessionmaker.begin() as session:
            state = await platform_state.get_state(session, platform, now)
            if state.state == "login_required":
                state.state, state.reason = "normal", None
            elif state.reason == "risk_and_login":
                state.reason = None
            state.warmup_until = (
                now + int(warmup_minutes * 60000) if warmup_minutes is not None else None
            )
            state.updated_at = now
            tasks = list(
                await session.scalars(
                    select(CollectionTask)
                    .where(
                        CollectionTask.platform == platform,
                        CollectionTask.status == "paused",
                        CollectionTask.reason == "login_lost",
                    )
                    .order_by(CollectionTask.queue_key.desc())
                )
            )
            changed = []
            for task in tasks:
                task.status, task.reason = "queued", None
                task.queue_key = await repo_tasks.queue_key(session, platform, first=True)
                task.updated_at = now
                await session.flush()
                changed.append((task.id, task.plan_id))
        for task_id, plan_id in changed:
            self._task_event(task_id, plan_id)
        self.events.publish("platform.updated", {"platform": platform})
        self.wake(platform)

    async def on_login_lost(self, platform: Platform) -> None:
        async with self.sessionmaker.begin() as session:
            state = await platform_state.get_state(session, platform, self.clock.now_ms())
            if state.state in {"locked", "cooldown", "page_changed"}:
                state.reason = "risk_and_login"
            else:
                state.state, state.reason = "login_required", "login_lost"
            state.updated_at = self.clock.now_ms()
        self.events.publish("platform.updated", {"platform": platform})
        self.wake(platform)

    async def on_probe(self, platform: Platform, ok: bool, detail: str | None) -> None:
        async with self.sessionmaker.begin() as session:
            state = await platform_state.get_state(session, platform, self.clock.now_ms())
            state.last_probe_at, state.last_probe_ok, state.last_probe_detail = (
                self.clock.now_ms(),
                ok,
                detail,
            )
            state.updated_at = self.clock.now_ms()
            if not ok:
                if state.state in {"locked", "cooldown", "page_changed"}:
                    state.reason = "risk_and_login"
                else:
                    state.state, state.reason = "login_required", "login_lost"
        self.events.publish("platform.updated", {"platform": platform})
        self.wake(platform)

    async def on_risk(self, platform: Platform, verdict: RiskVerdict, task_id: int | None) -> None:
        """写 risk_event，按规则冷却、锁定或转为需要登录。"""
        async with self.sessionmaker.begin() as session:
            await platform_state.record_risk(
                session, platform, verdict, task_id, self.clock.now_ms()
            )
        self.events.publish("risk_event.created", {"platform": platform, "task_id": task_id})
        self.events.publish("platform.updated", {"platform": platform})
        self.wake(platform)

    async def unlock(self, platform: Platform) -> None:
        async with self.sessionmaker.begin() as session:
            state = await platform_state.get_state(session, platform, self.clock.now_ms())
            if state.state == "locked":
                state.state = "login_required" if state.reason == "risk_and_login" else "normal"
                state.reason, state.locked_until, state.updated_at = None, None, self.clock.now_ms()
        self.events.publish("platform.updated", {"platform": platform})
        self.wake(platform)

    async def accept_page_change(self, platform: Platform) -> None:
        async with self.sessionmaker.begin() as session:
            state = await platform_state.get_state(session, platform, self.clock.now_ms())
            if state.state == "page_changed":
                state.state = "login_required" if state.reason == "risk_and_login" else "normal"
                state.reason, state.page_change_build = None, None
                state.updated_at = self.clock.now_ms()
        self.events.publish("platform.updated", {"platform": platform})
        self.wake(platform)

    # ---------- 读视图 ----------

    async def platform_view(self, session: AsyncSession, platform: Platform) -> PlatformView:
        return PlatformView.model_validate(
            await platform_state.view(session, platform, self.clock.now_ms(), self.tz, None)
        )

    async def quota_remaining(self, session: AsyncSession, platform: Platform) -> int:
        view = await self.platform_view(session, platform)
        return max(0, view.daily_quota - view.quota_used)

    async def task_views(
        self,
        session: AsyncSession,
        *,
        task_ids: list[int] | None = None,
        plan_id: int | None = None,
        conversation_id: int | None = None,
    ) -> list[TaskView]:
        return await repo_tasks.views(
            session,
            self.clock.now_ms(),
            self.tz,
            self.events,
            task_ids=task_ids,
            plan_id=plan_id,
            conversation_id=conversation_id,
        )

    def _task_event(self, task_id: int, plan_id: int | None) -> None:
        self.events.publish("task.updated", {"task_id": task_id, "plan_id": plan_id})

    async def _plan_finished(self, plan_id: int) -> None:
        async with self.sessionmaker() as session:
            unfinished = await session.scalar(
                select(CollectionTask.id)
                .where(
                    CollectionTask.plan_id == plan_id,
                    CollectionTask.status.in_(["queued", "running", "paused"]),
                )
                .limit(1)
            )
        if unfinished is None:
            for hook in self.plan_finished_hooks:
                await hook(plan_id)

    async def _transition(self, task_id: int, action: str) -> TaskView:
        async with self.sessionmaker() as session:
            task = await session.get(CollectionTask, task_id)
            if task is None:
                raise LookupError("任务不存在")
            platform = cast(Platform, task.platform)
        async with self._locks.setdefault(platform, asyncio.Lock()):
            return await self._transition_locked(task_id, action)

    async def _transition_locked(self, task_id: int, action: str) -> TaskView:
        async with self.sessionmaker() as session:
            task = await session.get(CollectionTask, task_id)
            if task is None:
                raise LookupError("任务不存在")
            platform = cast(Platform, task.platform)
            if action == "pause" and task.status not in {"queued", "running"}:
                raise InvalidTransition("任务不能暂停")
            if action == "resume" and task.status != "paused":
                raise InvalidTransition("任务不能继续")
        changed = False
        finished_running = False
        async with self.sessionmaker.begin() as session:
            task = await session.get(CollectionTask, task_id)
            if task is None:
                raise LookupError("任务不存在")
            if action == "resume":
                task.status, task.reason = "queued", None
                task.queue_key = await repo_tasks.queue_key(session, platform, first=True)
                changed = True
            elif task.status in {"queued", "running", "paused"}:
                finished_running = action == "stop" and task.status == "running"
                task.status = "paused" if action == "pause" else "stopped"
                task.reason = "user" if action == "pause" else None
                if action == "stop":
                    finished_at = self.clock.now_ms()
                    task.finished_at = finished_at
                    if finished_running:
                        state = await platform_state.get_state(session, platform, finished_at)
                        state.last_task_finished_at = finished_at
                changed = True
            if changed:
                task.updated_at = self.clock.now_ms()
            plan_id = task.plan_id
        if action != "resume" and self._active_ids.get(platform) == task_id:
            active = self._active.get(platform)
            if active is not None:
                active.cancel()
                await asyncio.gather(active, return_exceptions=True)
        if changed:
            self._task_event(task_id, plan_id)
            self.wake(platform)
        if finished_running:
            self.events.publish("platform.updated", {"platform": platform})
        if changed and action == "stop" and plan_id is not None:
            await self._plan_finished(plan_id)
        async with self.sessionmaker.begin() as session:
            return (await self.task_views(session, task_ids=[task_id]))[0]


from gleanery.api.schemas_collect import TaskOut as TaskView  # noqa: E402
from gleanery.collect import repo_tasks, worker  # noqa: E402
