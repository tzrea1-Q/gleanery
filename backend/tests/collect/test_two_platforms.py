import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import select

from gleanery.collect.plan import PlatformSection
from gleanery.collect.runtime import PlatformRuntime
from gleanery.collect.service import CollectService
from gleanery.events import EventBus
from gleanery.platforms.errors import PageChanged, RiskDetected
from gleanery.platforms.types import (
    CollectResult,
    ContentRecord,
    ContentRef,
    Depth,
    ParseReport,
    Platform,
    RiskKind,
    RiskVerdict,
    SearchPage,
)
from gleanery.store import Database, open_database
from gleanery.store.models import CollectionPlan, Dataset, RiskEvent
from gleanery.store.repo_settings import set_setting


class Clock:
    def __init__(self) -> None:
        self.now = 100000

    def now_ms(self) -> int:
        return self.now

    async def sleep(self, seconds: float) -> None:
        await asyncio.Event().wait()


class Fetcher:
    def __init__(self, platform: Platform) -> None:
        self.platform: Platform = platform
        self.calls: list[str] = []
        self.errors: list[Exception] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def search(self, keyword, sort, time_range, ctx) -> AsyncIterator[SearchPage]:
        if False:
            yield SearchPage(items=[])

    async def collect_content(self, ref, depth, ctx) -> CollectResult:
        self.calls.append(ref.platform_id)
        self.entered.set()
        await self.release.wait()
        if self.errors:
            raise self.errors.pop(0)
        return CollectResult(
            content=ContentRecord(
                platform=self.platform,
                platform_id=ref.platform_id,
                url=ref.url,
                kind="video" if self.platform == "bili" else "image_text",
                title=ref.platform_id,
                completeness="detail",
            ),
            comments=[],
            subtitles=[],
            report=ParseReport(items=1),
        )

    async def close(self) -> None:
        pass


class Runtime:
    platforms = frozenset({"bili", "xhs"})

    def __init__(self) -> None:
        self.fetchers = {platform: Fetcher(platform) for platform in ("bili", "xhs")}

    def fetcher(self, platform: Platform) -> Fetcher:
        return self.fetchers[platform]


class Scenario:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.clock = Clock()
        self.runtime = Runtime()
        self.service = CollectService(
            db.sessionmaker,
            EventBus(),
            self.clock,
            cast(PlatformRuntime, self.runtime),
            app_version="测试",
            tz=UTC,
        )
        self.finished: list[int] = []

        async def finished(plan_id: int) -> None:
            self.finished.append(plan_id)

        self.service.plan_finished_hooks.append(finished)

    async def plan(self, suffix: str, count: int = 1) -> tuple[int, list[int]]:
        sections = [
            PlatformSection(platform=platform, quantity=0, depth=Depth(detail=True))
            for platform in ("bili", "xhs")
        ]
        refs: dict[Platform, list[ContentRef]] = {
            section.platform: [
                ContentRef(
                    platform=section.platform,
                    platform_id=f"{suffix}-{index}",
                    url=f"{suffix}-{index}",
                )
                for index in range(count)
            ]
            for section in sections
        }
        async with self.db.sessionmaker.begin() as session:
            dataset = await session.get(Dataset, 1)
            assert dataset is not None
            plan = CollectionPlan(
                status="confirmed",
                version=1,
                body={"title": suffix},
                created_at=self.clock.now,
                updated_at=self.clock.now,
            )
            session.add(plan)
            await session.flush()
            plan_id = plan.id
            ids = await self.service.enqueue_plan(
                session, plan, dataset, sections, refs, self.clock.now
            )
        for platform in ("bili", "xhs"):
            self.service.wake(platform)
        return plan_id, ids

    async def views(self, ids: list[int]):
        async with self.db.sessionmaker() as session:
            return await self.service.task_views(session, task_ids=ids)

    async def platform(self, platform: Platform):
        async with self.db.sessionmaker() as session:
            return await self.service.platform_view(session, platform)

    async def wait(self, ids: list[int], predicate: Callable) -> None:
        async with asyncio.timeout(5):
            while not predicate(await self.views(ids)):  # noqa: ASYNC110
                await asyncio.sleep(0.01)

    def advance(self, milliseconds: int) -> None:
        self.clock.now += milliseconds
        for platform in ("bili", "xhs"):
            self.service.wake(platform)


@pytest.fixture
async def scenario(tmp_path: Path) -> AsyncIterator[Scenario]:
    db = await open_database(tmp_path)
    test = Scenario(db)
    async with db.sessionmaker.begin() as session:
        session.add(Dataset(id=1, name="测试", description="", created_at=test.clock.now))
    try:
        yield test
    finally:
        await test.service.stop()
        await db.close()


def risk(kind: RiskKind = "risk") -> RiskDetected:
    return RiskDetected(RiskVerdict(kind=kind, signal="测试风控", signal_type="code"))


async def test_parallel(scenario: Scenario) -> None:
    """同一计划的不同平台并行，全部终态后只通知一次。"""
    for fetcher in scenario.runtime.fetchers.values():
        fetcher.release.clear()
    plan, ids = await scenario.plan("并行")
    await scenario.service.start()
    await scenario.wait(ids, lambda views: all(view.status == "running" for view in views))
    assert not scenario.finished
    scenario.runtime.fetchers["bili"].release.set()
    await scenario.wait(ids, lambda views: views[0].status == "completed")
    assert not scenario.finished
    scenario.runtime.fetchers["xhs"].release.set()
    await scenario.wait(ids, lambda views: all(view.status == "completed" for view in views))
    async with asyncio.timeout(5):
        while not scenario.finished:  # noqa: ASYNC110
            await asyncio.sleep(0.01)
    assert scenario.finished == [plan]


async def check_risk_isolation(scenario: Scenario, platform: Platform, minutes: int) -> None:
    other: Platform = "xhs" if platform == "bili" else "bili"
    scenario.runtime.fetchers[platform].errors.append(risk())
    plan, ids = await scenario.plan("风控", count=2)
    await scenario.service.start()
    await scenario.wait(
        ids, lambda views: {view.status for view in views} == {"paused", "completed"}
    )
    views = {view.platform: view for view in await scenario.views(ids)}
    assert views[platform].reason == "risk"
    assert views[other].progress.processed == 2
    state = await scenario.platform(platform)
    assert state.state == "cooldown"
    assert state.cooldown_until == scenario.clock.now + minutes * 60000
    async with scenario.db.sessionmaker() as session:
        events = list(await session.scalars(select(RiskEvent)))
        assert [(event.platform, event.task_id, event.outcome) for event in events] == [
            (platform, views[platform].id, "cooldown")
        ]
    assert plan not in scenario.finished
    _, next_ids = await scenario.plan("后续")
    scenario.advance((minutes + 1) * 60000)
    await scenario.wait(
        next_ids,
        lambda views: next(view for view in views if view.platform == other).status == "completed",
    )
    views = {view.platform: view for view in await scenario.views(next_ids)}
    assert views[platform].status == "queued"
    assert views[platform].wait_reason == "blocked_by_risk_pause"
    assert plan not in scenario.finished
    await scenario.service.stop_tasks(task_id=ids[0 if platform == "bili" else 1])
    await scenario.wait(next_ids, lambda views: all(view.status == "completed" for view in views))


async def test_bili_risk_isolated(scenario: Scenario) -> None:
    """B 站风控暂停仅阻塞本平台，冷却结束仍须用户选择。"""
    await check_risk_isolation(scenario, "bili", 30)


async def test_xhs_risk_isolated(scenario: Scenario) -> None:
    """小红书风控暂停仅阻塞本平台，冷却结束仍须用户选择。"""
    await check_risk_isolation(scenario, "xhs", 120)


async def test_xhs_second_risk_manual_unlock(scenario: Scenario) -> None:
    """小红书 24 小时内再次风控后须手动解锁，B 站不受影响。"""
    fetcher = scenario.runtime.fetchers["xhs"]
    fetcher.errors.extend([risk(), risk()])
    _, ids = await scenario.plan("两次风控")
    await scenario.service.start()
    await scenario.wait(
        ids, lambda views: views[0].status == "completed" and views[1].status == "paused"
    )
    scenario.advance(120 * 60000)
    await scenario.service.resume(ids[1])
    await scenario.wait(ids, lambda views: views[1].status == "paused" and len(fetcher.calls) == 2)
    state = await scenario.platform("xhs")
    assert state.state == "locked" and state.locked_until is None
    _, next_ids = await scenario.plan("锁定中")
    scenario.advance(25 * 3600000)
    await scenario.wait(next_ids, lambda views: views[0].status == "completed")
    assert (await scenario.views(next_ids))[1].wait_reason == "locked"
    assert (await scenario.platform("xhs")).state == "locked"
    await scenario.service.unlock("xhs")
    assert (await scenario.platform("xhs")).state == "normal"
    await scenario.service.stop_tasks(task_id=ids[1])
    await scenario.wait(next_ids, lambda views: views[1].status == "completed")


async def test_xhs_risk_and_login(scenario: Scenario) -> None:
    """小红书游客形态按风控冷却，同时要求登录：冷却期间平台状态为冷却中、等待原因为需要登录，
    冷却到期仍未扫码就转为需要登录（M1 的设计：扫码只清掉登录要求，不提前结束冷却）。B 站照常完成。"""
    scenario.runtime.fetchers["xhs"].errors.append(risk("risk_and_login"))
    plan, ids = await scenario.plan("登录")
    await scenario.service.start()
    await scenario.wait(
        ids, lambda views: views[0].status == "completed" and views[1].status == "paused"
    )
    assert (await scenario.views(ids))[1].reason == "risk"
    state = await scenario.platform("xhs")
    assert state.state == "cooldown"
    assert state.wait_reason == "login_required"
    async with scenario.db.sessionmaker() as session:
        event = await session.scalar(select(RiskEvent))
        assert event is not None and event.outcome == "cooldown"
    assert plan not in scenario.finished
    scenario.advance(120 * 60000)
    assert (await scenario.platform("xhs")).state == "login_required"


async def test_xhs_page_changed(scenario: Scenario) -> None:
    """页面改版只搁置对应平台，两任务终态后通知一次。"""
    scenario.runtime.fetchers["xhs"].errors.append(PageChanged("页面改版"))
    plan, ids = await scenario.plan("改版")
    await scenario.service.start()
    await scenario.wait(
        ids, lambda views: views[0].status == "completed" and views[1].status == "failed"
    )
    assert (await scenario.views(ids))[1].reason == "page_changed"
    assert (await scenario.platform("xhs")).state == "page_changed"
    async with asyncio.timeout(5):
        while not scenario.finished:  # noqa: ASYNC110
            await asyncio.sleep(0.01)
    assert scenario.finished == [plan]


async def test_daily_quotas_are_independent(scenario: Scenario) -> None:
    """每日额度按平台独立，任务中耗尽后在本地零点续跑。"""
    async with scenario.db.sessionmaker.begin() as session:
        await set_setting(session, "collect.rate_limits.xhs", {"daily_quota": 1})
    _, ids = await scenario.plan("额度", count=2)
    await scenario.service.start()
    await scenario.wait(
        ids,
        lambda views: views[0].status == "completed" and views[1].wait_reason == "quota_exhausted",
    )
    assert (await scenario.views(ids))[1].progress.processed == 1
    assert (await scenario.platform("bili")).quota_used == 2
    scenario.advance(86400000 - scenario.clock.now)
    await scenario.wait(ids, lambda views: views[1].status == "completed")
    assert len(scenario.runtime.fetchers["xhs"].calls) == 2


async def test_minimum_intervals_are_independent(scenario: Scenario) -> None:
    """平台间最小任务间隔独立：小红书 30 分钟，B 站 10 分钟。"""
    _, ids = await scenario.plan("首次")
    await scenario.service.start()
    await scenario.wait(ids, lambda views: all(view.status == "completed" for view in views))
    _, next_ids = await scenario.plan("间隔")
    views = await scenario.views(next_ids)
    assert [view.wait_reason for view in views] == ["min_interval", "min_interval"]
    assert [view.wait_until for view in views] == [
        scenario.clock.now + 10 * 60000,
        scenario.clock.now + 30 * 60000,
    ]
    scenario.advance(10 * 60000)
    await scenario.wait(next_ids, lambda views: views[0].status == "completed")
    assert (await scenario.views(next_ids))[1].wait_reason == "min_interval"
    scenario.advance(20 * 60000)
    await scenario.wait(next_ids, lambda views: views[1].status == "completed")
