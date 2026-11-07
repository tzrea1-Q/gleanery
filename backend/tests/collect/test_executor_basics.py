from datetime import UTC
from pathlib import Path

import pytest

from gleanery.collect import platform_state, worker
from gleanery.collect.pacer import Pacer
from gleanery.collect.service import CollectService
from gleanery.collect.types import DEFAULT_RATE_LIMITS, TaskProgress
from gleanery.events import EventBus
from gleanery.platforms.errors import PageChanged
from gleanery.platforms.types import ParseReport, RiskVerdict
from gleanery.store import open_database
from gleanery.store.models import CollectionTask, Dataset, PlatformState


class FakeClock:
    def __init__(self) -> None:
        self.sleeps: list[float] = []

    def now_ms(self) -> int:
        return 1234

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


async def test_pacer_uses_clock_and_each_interval() -> None:
    clock = FakeClock()
    limits = DEFAULT_RATE_LIMITS["bili"].model_copy(
        update={"page_interval": (1, 1), "comment_page_interval": (2, 2), "long_rest": (3, 3)}
    )
    pacer = Pacer(clock, limits)
    await pacer.wait("page")
    await pacer.wait("comment_page")
    await pacer.long_rest()
    assert clock.sleeps == [1, 2, 3]


async def test_restart_marks_running_and_clears_old_build(tmp_path: Path) -> None:
    database = await open_database(tmp_path)
    try:
        async with database.sessionmaker.begin() as session:
            dataset = Dataset(name="测试", description="", created_at=1)
            session.add(dataset)
            await session.flush()
            session.add_all(
                [
                    CollectionTask(
                        dataset_id=dataset.id,
                        platform="bili",
                        status="running",
                        queue_key=1,
                        snapshot={},
                        progress={},
                        created_at=1,
                        updated_at=1,
                    ),
                    PlatformState(
                        platform="bili", state="page_changed", page_change_build="old", updated_at=1
                    ),
                    PlatformState(
                        platform="xhs", state="page_changed", page_change_build="new", updated_at=1
                    ),
                ]
            )
        bus = EventBus()
        service = CollectService(database.sessionmaker, bus, FakeClock(), None, app_version="new")
        await service.start()
        async with database.sessionmaker() as session:
            task = await session.get(CollectionTask, 1)
            old_state = await session.get(PlatformState, "bili")
            same_state = await session.get(PlatformState, "xhs")
            assert task is not None and (task.status, task.reason) == ("paused", "app_restart")
            assert old_state is not None and old_state.state == "normal"
            assert same_state is not None and same_state.state == "page_changed"
        assert bus._next_id == 3
    finally:
        await database.close()


async def test_risk_lock_and_timed_recovery(tmp_path: Path) -> None:
    database = await open_database(tmp_path)
    try:
        verdict = RiskVerdict(kind="risk", signal="412", signal_type="status")
        bus = EventBus()
        async with database.sessionmaker.begin() as session:
            await platform_state.record_risk(session, "bili", verdict, None, 1000)
            await session.flush()
            await platform_state.record_risk(session, "bili", verdict, None, 2000)
        async with database.sessionmaker.begin() as session:
            locked = await platform_state.view(session, "bili", 3000, UTC, bus)
            assert locked["wait_reason"] == "locked"
            resumed = await platform_state.view(session, "bili", 2000 + 6 * 3600000, UTC, bus)
            assert resumed["state"] == "normal"
    finally:
        await database.close()


def test_page_change_ratio_uses_minimum_sample() -> None:
    progress = TaskProgress()
    worker.check_report(progress, ParseReport(items=7, skipped_missing_core=3))
    with pytest.raises(PageChanged):
        worker.check_report(progress, ParseReport(items=1, missing_fields={"likes": 1}))
    assert progress.parse_stats["likes"] == 1


async def test_manual_lock_does_not_expire(tmp_path: Path) -> None:
    database = await open_database(tmp_path)
    bus = EventBus()
    verdict = RiskVerdict(kind="risk", signal="461", signal_type="status")
    try:
        async with database.sessionmaker.begin() as session:
            await platform_state.record_risk(session, "xhs", verdict, None, 1000)
            await session.flush()
            await platform_state.record_risk(session, "xhs", verdict, None, 2000)
        async with database.sessionmaker.begin() as session:
            state = await platform_state.view(session, "xhs", 2000 + 72 * 3600000, UTC, bus)
            assert state["wait_reason"] == "locked" and state["wait_until"] is None
        service = CollectService(database.sessionmaker, bus, FakeClock(), None, app_version="new")
        await service.unlock("xhs")
        async with database.sessionmaker.begin() as session:
            assert (await service.platform_view(session, "xhs")).state == "normal"
    finally:
        await database.close()


async def test_read_views_do_not_publish(tmp_path: Path) -> None:
    """读接口不提交会话；若读的时候发 platform.updated，前端会无限刷新。"""
    db = await open_database(tmp_path)
    events = EventBus()
    published: list[str] = []
    original = events.publish

    def spy(type, data=None):
        published.append(type)
        return original(type, data)

    events.publish = spy  # type: ignore[method-assign]
    service = CollectService(db.sessionmaker, events, FakeClock(), None, app_version="a", tz=UTC)
    try:
        for _ in range(3):
            async with db.sessionmaker() as session:
                view = await service.platform_view(session, "bili")
                await service.task_views(session, conversation_id=1)
            assert view.state == "normal"
        assert published == []
    finally:
        await db.close()
