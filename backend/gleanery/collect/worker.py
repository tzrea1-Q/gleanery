from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, cast

from sqlalchemy import func, select

from gleanery.collect import platform_state, repo_tasks
from gleanery.collect.estimate import remaining_seconds
from gleanery.collect.pacer import Pacer
from gleanery.collect.plan import PlatformSection
from gleanery.collect.settings import load_rate_limits
from gleanery.collect.types import (
    NETWORK_RETRY_DELAYS,
    PAGE_CHANGE_MISSING_CORE_RATIO,
    Phase,
    TaskProgress,
    TaskSnapshot,
)
from gleanery.platforms.errors import (
    BrowserDisconnected,
    PageChanged,
    ProfileInUse,
    RiskDetected,
    TransientError,
)
from gleanery.platforms.types import (
    CaptureSink,
    ContentRecord,
    ContentRef,
    Depth,
    Fetcher,
    ParseReport,
    Platform,
)
from gleanery.platforms.types import Pacer as PacerProtocol
from gleanery.store import repo_content, repo_datasets
from gleanery.store.models import CollectionTask, Content, DatasetItem, TaskItem
from gleanery.store.repo_raw_capture import RawCaptureSink

if TYPE_CHECKING:
    from gleanery.collect.service import CollectService

logger = logging.getLogger(__name__)
DEPTH_KEY = "gleanery_collected_depth"


class ReportPageChanged(PageChanged):
    def __init__(self, reason: str, progress: TaskProgress) -> None:
        super().__init__(reason)
        self.progress = progress


def satisfies(content: Content | None, depth: Depth) -> bool:
    if content is None:
        return False
    if not depth.opens_page:
        return True
    if content.completeness != "detail":
        return False
    recorded = content.ext.get(DEPTH_KEY, {})
    if not isinstance(recorded, dict):
        recorded = {}
    return (
        int(recorded.get("comments", 0)) >= depth.comments
        and (not depth.sub_comments or bool(recorded.get("sub_comments")))
        and (
            not depth.sub_comments
            or int(recorded.get("sub_comments_per_root", 0)) >= depth.sub_comments_per_root
        )
        and (not depth.subtitles or bool(recorded.get("subtitles")))
    )


class Context:
    def __init__(self, service: CollectService, task_id: int, pacer: Pacer) -> None:
        self.service = service
        self.task_id = task_id
        self.sink: CaptureSink = RawCaptureSink(service.sessionmaker, task_id)
        self.pacer: PacerProtocol = pacer
        self.rest = pacer
        self.limits = pacer.limits
        self.last_log: str | None = None

    def log(self, message: str) -> None:
        # 只记在内存里，随下一次进度落库一起写：单独落库会和进度的读-改-写交错，覆盖掉计数。
        self.last_log = message
        logger.info("%s", message)


async def sleep_or_wake(service: CollectService, platform: Platform, until: int | None) -> None:
    wake = service._wake_events[platform]
    if wake.is_set():
        wake.clear()
        return
    wake_task = asyncio.create_task(wake.wait())
    timer = (
        None
        if until is None
        else asyncio.create_task(
            service.clock.sleep(max(0, (until - service.clock.now_ms()) / 1000))
        )
    )
    tasks = [wake_task] if timer is None else [wake_task, timer]
    woken = False
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        woken = wake_task.done() and not wake_task.cancelled()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if woken:
            wake.clear()


async def run(service: CollectService, platform: Platform) -> None:
    while True:
        try:
            await _step(service, platform)
        except asyncio.CancelledError:
            raise
        except Exception:
            # 调度本身出错（如读库失败）不能让本平台的 worker 永久退出：记日志，稍后重试。
            logger.exception("采集调度出错 platform=%s", platform)
            await service.clock.sleep(5)


async def _step(service: CollectService, platform: Platform) -> None:
    """调度循环的一轮：平台可执行就取队首任务跑完，否则睡到截止时间或被唤醒。"""
    async with service.sessionmaker.begin() as session:
        status = await platform_state.view(
            session, platform, service.clock.now_ms(), service.tz, service.events
        )
        task_id = None
        if status["wait_reason"] is None:
            task_id = await session.scalar(
                select(CollectionTask.id)
                .where(CollectionTask.platform == platform, CollectionTask.status == "queued")
                .order_by(CollectionTask.queue_key, CollectionTask.id)
                .limit(1)
            )
    if task_id is None:
        await sleep_or_wake(service, platform, status["wait_until"])
        return
    active = asyncio.create_task(execute(service, platform, task_id))
    service._active[platform] = active
    service._active_ids[platform] = task_id
    try:
        await active
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise
    finally:
        service._active.pop(platform, None)
        service._active_ids.pop(platform, None)


async def retry[T](service: CollectService, operation: Callable[[], Awaitable[T]]) -> T:
    for delay in (*NETWORK_RETRY_DELAYS, None):
        try:
            return await operation()
        except TransientError:
            if delay is None:
                raise
            await service.clock.sleep(delay)
    raise AssertionError


def check_report(progress: TaskProgress, report: ParseReport) -> None:
    progress.skipped_missing_core += report.skipped_missing_core
    for key, value in report.missing_fields.items():
        progress.parse_stats[key] = progress.parse_stats.get(key, 0) + value
    items = progress.parse_stats.get("__items", 0) + report.items
    progress.parse_stats["__items"] = items
    total = items + progress.skipped_missing_core
    reason = None
    if report.nonempty_response and report.items == 0:
        reason = "empty_parse"
    elif total > 10 and progress.skipped_missing_core / total > PAGE_CHANGE_MISSING_CORE_RATIO:
        reason = "missing_core"
    if reason is not None:
        raise ReportPageChanged(reason, progress)


def in_range(service: CollectService, section: PlatformSection, record: ContentRecord) -> bool:
    bounds = section.time_range
    if bounds is None:
        return True
    if record.published_at is None:
        return False
    day = datetime.fromtimestamp(record.published_at / 1000, service.tz).date()
    today = datetime.fromtimestamp(service.clock.now_ms() / 1000, service.tz).date()
    return not (
        (bounds.last_days is not None and day < today - timedelta(days=bounds.last_days - 1))
        or (bounds.start is not None and day.isoformat() < bounds.start)
        or (bounds.end is not None and day.isoformat() > bounds.end)
        or (bounds.last_days is not None and day > today)
    )


async def execute(service: CollectService, platform: Platform, task_id: int) -> None:
    fetcher: Fetcher | None = None
    ctx: Context | None = None
    try:
        async with (
            service._locks.setdefault(platform, asyncio.Lock()),
            service.sessionmaker.begin() as session,
        ):
            task = await session.get(CollectionTask, task_id)
            if task is None or task.status != "queued":
                return
            now = service.clock.now_ms()
            snapshot = TaskSnapshot.model_validate(task.snapshot)
            if task.started_at is None:
                snapshot.rate_limits = await load_rate_limits(session, platform)
                task.snapshot = snapshot.model_dump(mode="json")
                task.started_at = now
            task.status, task.reason, task.updated_at = "running", None, now
            progress = TaskProgress.model_validate(task.progress)
            if progress.phase == "waiting":
                progress.phase = "search"
            task.progress = progress.model_dump()
        service._task_event(task_id, task.plan_id)
        assert service.runtime is not None
        fetcher = service.runtime.fetcher(platform)
        ctx = Context(service, task_id, Pacer(service.clock, snapshot.rate_limits))
        section = PlatformSection.model_validate(snapshot.section)
        await work_through(service, fetcher, ctx, task_id, section, progress)
    except asyncio.CancelledError:
        raise
    except RiskDetected as error:
        await service.on_risk(platform, error.verdict, task_id)
        await finish(
            service,
            task_id,
            "paused",
            "login_lost" if error.verdict.kind == "login_required" else "risk",
        )
    except PageChanged as error:
        # 出错的步骤、选择器或接口路径只写本地日志。
        logger.warning("页面改版 task_id=%s：%s %s", task_id, error.reason, error.detail or "")
        async with service.sessionmaker.begin() as session:
            state = await platform_state.get_state(session, platform, service.clock.now_ms())
            state.state, state.page_change_build, state.updated_at = (
                "page_changed",
                service.app_version,
                service.clock.now_ms(),
            )
            task = await session.get(CollectionTask, task_id)
            if task is not None and isinstance(error, ReportPageChanged):
                task.progress = error.progress.model_dump()
        service.events.publish("platform.updated", {"platform": platform})
        await finish(service, task_id, "failed", "page_changed")
    except (BrowserDisconnected, ProfileInUse):
        await finish(service, task_id, "paused", "browser_disconnected")
    except Exception:
        logger.exception("采集任务失败 task_id=%s", task_id)
        await finish(service, task_id, "failed", "network")
    finally:
        if fetcher is not None:
            try:
                await fetcher.close()
            except Exception:
                logger.exception("关闭取数器失败 task_id=%s", task_id)


async def enter_phase(
    service: CollectService, task_id: int, phase: Phase, keyword: str | None = None
) -> None:
    async with service.sessionmaker.begin() as session:
        task = await session.get(CollectionTask, task_id)
        assert task is not None
        progress = TaskProgress.model_validate(task.progress)
        progress.phase = phase
        if keyword is not None:
            progress.keyword = keyword
        task.progress = progress.model_dump()
    service._task_event(task_id, task.plan_id)


async def work_through(
    service: CollectService,
    fetcher: Fetcher,
    ctx: Context,
    task_id: int,
    section: PlatformSection,
    progress: TaskProgress,
) -> None:
    """一个关键词搜完就打开它的内容，再搜下一个：页面还停在结果页上，不用回去重搜。"""
    keywords = section.keywords
    start = keywords.index(progress.keyword) if progress.keyword in keywords else 0
    if progress.phase == "content":
        start += 1
    if start >= len(keywords):
        await enter_phase(service, task_id, "content")
    # 指定内容是直接打开的，排在搜索前才不会把页面带离结果页。
    if not await contents(service, fetcher, ctx, task_id, section, start < len(keywords)):
        return
    for index in range(start, len(keywords)):
        if not await search(service, fetcher, ctx, task_id, section, index):
            return
        await enter_phase(service, task_id, "content")
        more_keywords = index + 1 < len(keywords)
        if not await contents(service, fetcher, ctx, task_id, section, more_keywords):
            return
    await finish(service, task_id, "completed", None)


async def search(
    service: CollectService,
    fetcher: Fetcher,
    ctx: Context,
    task_id: int,
    section: PlatformSection,
    index: int,
) -> bool:
    keyword = section.keywords[index]
    await enter_phase(service, task_id, "search", keyword)
    async with service.sessionmaker() as session:
        sources = list(
            await session.scalars(
                select(TaskItem.source).where(
                    TaskItem.task_id == task_id, TaskItem.source.like("search:%")
                )
            )
        )
    prior = sum(sources.count(f"search:{previous}") for previous in section.keywords[:index])
    remaining = max(0, section.quantity - prior)
    target = math.ceil(remaining / (len(section.keywords) - index))
    found = sources.count(f"search:{keyword}")
    if found >= target:
        return True
    iterator = fetcher.search(keyword, section.sort, section.time_range, ctx)
    pages = 0
    quota_blocked = False
    needs_reset = False

    async def next_page(current_keyword: str, page_count: int):
        nonlocal iterator, needs_reset
        try:
            if needs_reset:
                if isinstance(iterator, AsyncGenerator):
                    await iterator.aclose()
                iterator = fetcher.search(current_keyword, section.sort, section.time_range, ctx)
                for _ in range(page_count):
                    await anext(iterator)
                needs_reset = False
            return await anext(iterator)
        except TransientError:
            needs_reset = True
            raise

    try:
        while found < target and pages < math.ceil(target / 20) + 10:
            try:
                page = await retry(
                    service,
                    lambda keyword=keyword, pages=pages: next_page(keyword, pages),
                )
            except StopAsyncIteration:
                break
            pages += 1
            async with service.sessionmaker.begin() as session:
                task = await session.get(CollectionTask, task_id)
                assert task is not None
                progress = TaskProgress.model_validate(task.progress)
                ctx.log(f"搜索「{keyword}」第 {pages} 页")
                progress.last_log = ctx.last_log
                progress.eta_seconds = remaining_seconds(section, ctx.limits, 0, searching=True)
                check_report(progress, page.report)
                state = await platform_state.get_state(
                    session, section.platform, service.clock.now_ms()
                )
                for record in page.contents:
                    if found >= target or not in_range(service, section, record):
                        continue
                    exists = await session.scalar(
                        select(TaskItem.id).where(
                            TaskItem.task_id == task_id,
                            TaskItem.platform_id == record.platform_id,
                        )
                    )
                    if exists is not None:
                        continue
                    old = await session.scalar(
                        select(Content).where(
                            Content.platform == section.platform,
                            Content.platform_id == record.platform_id,
                        )
                    )
                    satisfied = satisfies(old, section.depth)
                    if (
                        not section.depth.opens_page
                        and not satisfied
                        and state.quota_used
                        >= TaskSnapshot.model_validate(task.snapshot).rate_limits.daily_quota
                    ):
                        task.status = "queued"
                        task.queue_key = await repo_tasks.queue_key(
                            session, section.platform, first=True
                        )
                        quota_blocked = True
                        break
                    ids = await repo_content.upsert_contents(
                        session, [record], task_id, service.clock.now_ms()
                    )
                    await repo_datasets.add_to_dataset(
                        session,
                        task.dataset_id,
                        [ids[record.platform_id]],
                        task_id,
                        service.clock.now_ms(),
                    )
                    ref = ContentRef(
                        platform=section.platform,
                        platform_id=record.platform_id,
                        url=record.url,
                        ext=record.ext,
                    )
                    item_state = (
                        "skipped"
                        if satisfied
                        else ("pending" if section.depth.opens_page else "done")
                    )
                    seq = (
                        int(
                            await session.scalar(
                                select(func.max(TaskItem.seq)).where(TaskItem.task_id == task_id)
                            )
                            or 0
                        )
                        + 1
                    )
                    session.add(
                        TaskItem(
                            task_id=task_id,
                            platform_id=record.platform_id,
                            content_id=ids[record.platform_id],
                            ref=ref.model_dump(mode="json"),
                            source=f"search:{keyword}",
                            seq=seq,
                            state=item_state,
                            skip_reason="already_satisfied" if satisfied else None,
                        )
                    )
                    if item_state == "done":
                        state.quota_used += 1
                        progress.quota_counted += 1
                    if item_state != "pending":
                        progress.processed += 1
                    progress.discovered += 1
                    found += 1
                task.progress = progress.model_dump()
                task.updated_at = service.clock.now_ms()
                dataset_id, plan_id = task.dataset_id, task.plan_id
            service._task_event(task_id, plan_id)
            service.events.publish("dataset.updated", {"dataset_id": dataset_id})
            if not section.depth.opens_page:
                service.events.publish("platform.updated", {"platform": section.platform})
            if quota_blocked:
                return False
            if not page.has_more:
                break
    finally:
        if isinstance(iterator, AsyncGenerator):
            await iterator.aclose()
    return True


async def contents(
    service: CollectService,
    fetcher: Fetcher,
    ctx: Context,
    task_id: int,
    section: PlatformSection,
    more_keywords: bool,
) -> bool:
    while True:
        async with service.sessionmaker.begin() as session:
            task = await session.get(CollectionTask, task_id)
            assert task is not None
            item = await session.scalar(
                select(TaskItem)
                .where(TaskItem.task_id == task_id, TaskItem.state == "pending")
                .order_by(TaskItem.seq)
                .limit(1)
            )
            if item is None:
                break
            existing = await session.scalar(
                select(Content).where(
                    Content.platform == section.platform, Content.platform_id == item.platform_id
                )
            )
            if satisfies(existing, section.depth):
                assert existing is not None
                await repo_datasets.add_to_dataset(
                    session, task.dataset_id, [existing.id], task_id, service.clock.now_ms()
                )
                item.content_id, item.state, item.skip_reason = (
                    existing.id,
                    "skipped",
                    "already_satisfied",
                )
                progress = TaskProgress.model_validate(task.progress)
                progress.processed += 1
                ctx.log(f"{item.platform_id} 已在内容库里，跳过")
                progress.last_log = ctx.last_log
                task.progress, task.updated_at = progress.model_dump(), service.clock.now_ms()
                service._task_event(task_id, task.plan_id)
                service.events.publish("dataset.updated", {"dataset_id": task.dataset_id})
                continue
            await platform_state.view(
                session, section.platform, service.clock.now_ms(), service.tz, service.events
            )
            state = await platform_state.get_state(
                session, section.platform, service.clock.now_ms()
            )
            if (
                state.quota_used
                >= TaskSnapshot.model_validate(task.snapshot).rate_limits.daily_quota
            ):
                task.status = "queued"
                task.queue_key = await repo_tasks.queue_key(session, section.platform, first=True)
                task.updated_at = service.clock.now_ms()
                service._task_event(task_id, task.plan_id)
                return False
            item_id, ref = item.id, ContentRef.model_validate(item.ref)
        result = await retry(
            service, lambda ref=ref: fetcher.collect_content(ref, section.depth, ctx)
        )
        async with service.sessionmaker.begin() as session:
            task = await session.get(CollectionTask, task_id)
            item = await session.get(TaskItem, item_id)
            assert task is not None and item is not None
            if task.status != "running":
                return False
            progress = TaskProgress.model_validate(task.progress)
            check_report(progress, result.report)
            now = service.clock.now_ms()
            ids = await repo_content.upsert_contents(session, [result.content], task_id, now)
            content_id = ids[result.content.platform_id]
            content = await session.get(Content, content_id)
            assert content is not None
            recorded = content.ext.get(DEPTH_KEY, {})
            if not isinstance(recorded, dict):
                recorded = {}
            content.ext = {
                **content.ext,
                DEPTH_KEY: {
                    "comments": max(int(recorded.get("comments", 0)), section.depth.comments),
                    "sub_comments": bool(recorded.get("sub_comments"))
                    or section.depth.sub_comments,
                    "sub_comments_per_root": max(
                        int(recorded.get("sub_comments_per_root", 0)),
                        section.depth.sub_comments_per_root if section.depth.sub_comments else 0,
                    ),
                    "subtitles": bool(recorded.get("subtitles")) or section.depth.subtitles,
                },
            }
            await repo_content.upsert_comments(session, content_id, result.comments, task_id, now)
            await repo_content.upsert_subtitles(session, content_id, result.subtitles, now)
            item.content_id = content_id
            route = f"（{result.route}）" if result.route else ""
            out_of_range = section.time_range is not None and not in_range(
                service, section, result.content
            )
            if out_of_range:
                member = await session.get(DatasetItem, (task.dataset_id, content_id))
                if member is not None and member.task_id == task_id:
                    await session.delete(member)
                item.state, item.skip_reason = "skipped", "out_of_range"
                ctx.log(f"{result.content.platform_id} 发布时间不在范围内，未加入数据集{route}")
            else:
                await repo_datasets.add_to_dataset(
                    session, task.dataset_id, [content_id], task_id, now
                )
                item.state = "done"
                progress.processed += 1
                subtitles = (
                    f"，字幕 {len(result.subtitles)} 份" if section.platform == "bili" else ""
                )
                ctx.log(
                    f"已采 {result.content.platform_id}："
                    f"评论 {len(result.comments)} 条{subtitles}{route}"
                )
            state = await platform_state.get_state(session, section.platform, now)
            state.quota_used += 1
            progress.quota_counted += 1
            progress.comments += len(result.comments)
            progress.subtitles += len(result.subtitles)
            progress.last_log = ctx.last_log
            pending = await session.scalar(
                select(func.count())
                .select_from(TaskItem)
                .where(TaskItem.task_id == task_id, TaskItem.state == "pending")
            )
            progress.eta_seconds = remaining_seconds(
                section, ctx.limits, int(pending or 0), searching=more_keywords
            )
            task.progress, task.updated_at = progress.model_dump(), now
            snapshot = TaskSnapshot.model_validate(task.snapshot)
            plan_id, dataset_id = task.plan_id, task.dataset_id
        service._task_event(task_id, plan_id)
        service.events.publish("dataset.updated", {"dataset_id": dataset_id})
        service.events.publish("platform.updated", {"platform": section.platform})
        if (
            not out_of_range
            and snapshot.rate_limits.long_rest_every
            and progress.processed % snapshot.rate_limits.long_rest_every == 0
        ):
            await ctx.rest.long_rest()
    return True


async def finish(service: CollectService, task_id: int, status: str, reason: str | None) -> None:
    async with service.sessionmaker.begin() as session:
        task = await session.get(CollectionTask, task_id)
        if task is None or task.status != "running":
            return
        now = service.clock.now_ms()
        task.status, task.reason, task.updated_at = status, reason, now
        if status in {"completed", "failed", "stopped"}:
            task.finished_at = now
            progress = TaskProgress.model_validate(task.progress)
            # 最小间隔是给采过内容的任务降频的；还没碰内容就失败时，上一个任务的间隔照旧算。
            if status != "failed" or progress.quota_counted:
                state = await platform_state.get_state(session, cast(Platform, task.platform), now)
                state.last_task_finished_at = now
            if status == "completed":
                progress.phase = "done"
                task.progress = progress.model_dump()
        plan_id = task.plan_id
        platform = cast(Platform, task.platform)
    service._task_event(task_id, plan_id)
    if plan_id is not None and status in {"completed", "failed", "stopped"}:
        await service._plan_finished(plan_id)
    if status in {"completed", "failed", "stopped"}:
        service.events.publish("platform.updated", {"platform": platform})
        service.wake(platform)
