import asyncio
from collections.abc import AsyncIterator
from datetime import UTC
from pathlib import Path
from typing import cast

from sqlalchemy import select

from gleanery.collect import platform_state, worker
from gleanery.collect.plan import PlatformSection
from gleanery.collect.runtime import PlatformRuntime
from gleanery.collect.service import CollectService
from gleanery.collect.types import DEFAULT_RATE_LIMITS, TaskProgress, TaskSnapshot
from gleanery.events import EventBus
from gleanery.platforms.errors import RiskDetected, TransientError
from gleanery.platforms.types import (
    CollectResult,
    ContentRecord,
    ContentRef,
    Depth,
    ParseReport,
    RiskVerdict,
    SearchPage,
    TimeRange,
)
from gleanery.store import open_database, repo_content
from gleanery.store.models import CollectionTask, Dataset, PlatformState, TaskItem
from gleanery.store.repo_settings import set_setting


class Clock:
    def __init__(self) -> None:
        self.now = 100000
        self.delays: list[float] = []

    def now_ms(self) -> int:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.delays.append(seconds)
        self.now += int(seconds * 1000)
        await asyncio.sleep(0)


async def wait_ready(event: asyncio.Event) -> None:
    for _ in range(10):
        try:
            await asyncio.wait_for(event.wait(), timeout=0.1)
            return
        except TimeoutError:
            pass
    raise AssertionError("等待执行器超时")


def record(identifier: str) -> ContentRecord:
    return ContentRecord(
        platform="bili",
        platform_id=identifier,
        url=identifier,
        kind="video",
        title=identifier,
        completeness="summary",
    )


class Fetcher:
    platform = "bili"

    def __init__(self) -> None:
        self.pages: dict[str, list[SearchPage]] = {}
        self.calls: list[str] = []
        self.error: Exception | None = None
        self.entered = asyncio.Event()
        self.block = False
        self.block_ids: set[str] = set()
        self.route: str | None = None

    async def search(self, keyword, sort, time_range, ctx) -> AsyncIterator[SearchPage]:
        for page in self.pages.get(keyword, []):
            yield page

    async def collect_content(self, ref, depth, ctx) -> CollectResult:
        self.calls.append(ref.platform_id)
        self.entered.set()
        if self.block or ref.platform_id in self.block_ids:
            await asyncio.Event().wait()
        if self.error is not None:
            raise self.error
        return CollectResult(
            content=record(ref.platform_id).model_copy(update={"completeness": "detail"}),
            comments=[],
            subtitles=[],
            report=ParseReport(items=1),
            route=self.route,
        )

    async def close(self) -> None:
        pass


class Runtime:
    platforms = frozenset({"bili"})

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher_instance = fetcher

    def fetcher(self, platform):
        return self.fetcher_instance


async def setup(tmp_path: Path, section: PlatformSection, targets: list[str] | None = None):
    targets = targets or []
    db = await open_database(tmp_path)
    fetcher = Fetcher()
    clock = Clock()
    service = CollectService(
        db.sessionmaker,
        EventBus(),
        clock,
        cast(PlatformRuntime, Runtime(fetcher)),
        app_version="a",
        tz=UTC,
    )
    snapshot = TaskSnapshot(
        plan_title="测试",
        dataset_id=1,
        dataset_name="测试",
        section=section.model_dump(),
        confirmed_at=clock.now,
        rate_limits=DEFAULT_RATE_LIMITS["bili"],
    )
    async with db.sessionmaker.begin() as session:
        session.add(Dataset(id=1, name="测试", description="", created_at=clock.now))
        await session.flush()
        session.add(
            CollectionTask(
                id=1,
                dataset_id=1,
                platform="bili",
                status="queued",
                queue_key=1,
                snapshot=snapshot.model_dump(mode="json"),
                progress=TaskProgress(
                    planned=section.quantity + len(targets), discovered=len(targets)
                ).model_dump(),
                created_at=clock.now,
                updated_at=clock.now,
            )
        )
        await session.flush()
        for seq, identifier in enumerate(targets):
            ref = ContentRef(platform="bili", platform_id=identifier, url=identifier)
            session.add(
                TaskItem(
                    task_id=1,
                    platform_id=identifier,
                    ref=ref.model_dump(),
                    source="target",
                    seq=seq,
                    state="pending",
                )
            )
    return db, service, fetcher, clock


async def test_search_quota_carry_and_dedup(tmp_path: Path) -> None:
    section = PlatformSection(
        platform="bili", keywords=["a", "b"], quantity=4, depth=Depth(detail=False)
    )
    db, service, fetcher, _ = await setup(tmp_path, section)
    try:
        fetcher.pages = {
            "a": [SearchPage(contents=[record("1")], has_more=False, report=ParseReport(items=1))],
            "b": [
                SearchPage(
                    contents=[record("1"), record("2"), record("3"), record("4")],
                    has_more=False,
                    report=ParseReport(items=4),
                )
            ],
        }
        await worker.execute(service, "bili", 1)
        async with db.sessionmaker() as session:
            task = await session.get(CollectionTask, 1)
            items = list(await session.scalars(select(TaskItem).order_by(TaskItem.seq)))
            assert task is not None and task.status == "completed"
            assert [item.platform_id for item in items] == ["1", "2", "3", "4"]
            # 进度里的最近一条日志要有内容，界面和 Agent 都靠它看到执行到哪了。只要摘要时不打开内容页。
            assert task.progress["last_log"] == "搜索「b」第 1 页"
    finally:
        await db.close()


async def test_retry_then_fail(tmp_path: Path) -> None:
    section = PlatformSection(platform="bili", targets=["a"], quantity=0, depth=Depth())
    db, service, fetcher, clock = await setup(tmp_path, section, ["a"])
    try:
        fetcher.error = TransientError()
        await worker.execute(service, "bili", 1)
        async with db.sessionmaker() as session:
            task = await session.get(CollectionTask, 1)
            assert task is not None and (task.status, task.reason) == ("failed", "network")
            assert fetcher.calls == ["a", "a", "a"]
            assert clock.delays == [5, 15]
    finally:
        await db.close()


async def test_failure_before_any_content_keeps_the_previous_task_gap(tmp_path: Path) -> None:
    """只开了结果页就失败，没碰内容，不用再等 30 分钟。"""
    section = PlatformSection(platform="bili", keywords=["a"], quantity=1, depth=Depth())
    db, service, fetcher, clock = await setup(tmp_path, section)

    async def search(keyword, sort, time_range, ctx):
        raise RuntimeError("页面出错")
        yield

    fetcher.search = search
    try:
        async with db.sessionmaker.begin() as session:
            state = await platform_state.get_state(session, "bili", clock.now)
            state.last_task_finished_at = 123
        await worker.execute(service, "bili", 1)
        async with db.sessionmaker() as session:
            task = await session.get(CollectionTask, 1)
            state = await session.get(PlatformState, "bili")
            assert task is not None and (task.status, task.reason) == ("failed", "network")
            assert state is not None and state.last_task_finished_at == 123
    finally:
        await db.close()


async def test_failure_after_collecting_content_still_counts_for_the_task_gap(
    tmp_path: Path,
) -> None:
    section = PlatformSection(platform="bili", targets=["a", "b"], quantity=0, depth=Depth())
    db, service, fetcher, clock = await setup(tmp_path, section, ["a", "b"])
    collect = fetcher.collect_content

    async def detail(ref, depth, ctx):
        if ref.platform_id == "b":
            raise RuntimeError("页面出错")
        return await collect(ref, depth, ctx)

    fetcher.collect_content = detail
    try:
        await worker.execute(service, "bili", 1)
        async with db.sessionmaker() as session:
            task = await session.get(CollectionTask, 1)
            state = await session.get(PlatformState, "bili")
            assert task is not None and (task.status, task.reason) == ("failed", "network")
            assert state is not None and state.last_task_finished_at == clock.now
    finally:
        await db.close()


async def test_risk_pauses_and_blocks_queue(tmp_path: Path) -> None:
    section = PlatformSection(platform="bili", targets=["a"], quantity=0, depth=Depth())
    db, service, fetcher, clock = await setup(tmp_path, section, ["a"])
    try:
        fetcher.error = RiskDetected(RiskVerdict(kind="risk", signal="412", signal_type="status"))
        await worker.execute(service, "bili", 1)
        clock.now += 3600000
        async with db.sessionmaker.begin() as session:
            task = await session.get(CollectionTask, 1)
            status = await service.platform_view(session, "bili")
            assert task is not None and (task.status, task.reason) == ("paused", "risk")
            assert status.wait_reason == "blocked_by_risk_pause"
        await service.resume(1)
        async with db.sessionmaker.begin() as session:
            assert (await service.platform_view(session, "bili")).wait_reason is None
    finally:
        await db.close()


def trace_keywords(fetcher: Fetcher, per_keyword: int = 1) -> list[str]:
    """记下搜索和打开的先后：每个关键词的结果是 `<词>1`、`<词>2`……"""
    events: list[str] = []
    collect = fetcher.collect_content

    async def search(keyword, sort, time_range, ctx):
        events.append(f"搜 {keyword}")
        yield SearchPage(
            contents=[record(f"{keyword}{number + 1}") for number in range(per_keyword)],
            has_more=False,
            report=ParseReport(items=per_keyword),
        )

    async def detail(ref, depth, ctx):
        events.append(f"开 {ref.platform_id}")
        return await collect(ref, depth, ctx)

    fetcher.search = search
    fetcher.collect_content = detail
    return events


async def test_opens_a_keywords_contents_before_searching_the_next(tmp_path: Path) -> None:
    """搜完全部关键词再打开的话，前面的关键词都要回结果页，每次多 3 次搜索请求。"""
    section = PlatformSection(platform="bili", keywords=["a", "b"], quantity=4, depth=Depth())
    db, service, fetcher, _ = await setup(tmp_path, section)
    events = trace_keywords(fetcher, per_keyword=2)
    try:
        await worker.execute(service, "bili", 1)
        async with db.sessionmaker() as session:
            task = await session.get(CollectionTask, 1)
            assert task is not None and task.status == "completed"
            assert task.progress["phase"] == "done"
        assert events == ["搜 a", "开 a1", "开 a2", "搜 b", "开 b1", "开 b2"]
    finally:
        await db.close()


async def test_specified_contents_open_before_the_first_search(tmp_path: Path) -> None:
    """指定内容是直接打开的，排在搜索之后会把页面带离结果页。"""
    section = PlatformSection(
        platform="bili", keywords=["a"], targets=["t"], quantity=1, depth=Depth()
    )
    db, service, fetcher, _ = await setup(tmp_path, section, ["t"])
    events = trace_keywords(fetcher)
    try:
        await worker.execute(service, "bili", 1)
        assert events == ["开 t", "搜 a", "开 a1"]
    finally:
        await db.close()


async def test_resume_goes_on_from_the_keyword_it_stopped_at(tmp_path: Path) -> None:
    """a 搜不满目标也算搜完了，续跑不再重搜，余额顺延给 b。"""
    section = PlatformSection(platform="bili", keywords=["a", "b"], quantity=4, depth=Depth())
    db, service, fetcher, _ = await setup(tmp_path, section)
    events = trace_keywords(fetcher)
    try:
        fetcher.block_ids = {"a1"}
        active = asyncio.create_task(worker.execute(service, "bili", 1))
        service._active["bili"] = active
        service._active_ids["bili"] = 1
        await fetcher.entered.wait()
        assert (await service.pause(1)).status == "paused"
        service._active.clear()
        service._active_ids.clear()
        await service.resume(1)
        fetcher.block_ids = set()
        await worker.execute(service, "bili", 1)
        assert events == ["搜 a", "开 a1", "开 a1", "搜 b", "开 b1"]
    finally:
        await db.close()


async def test_eta_covers_keywords_not_searched_yet(tmp_path: Path) -> None:
    section = PlatformSection(platform="bili", keywords=["a", "b"], quantity=2, depth=Depth())
    db, service, fetcher, _ = await setup(tmp_path, section)
    trace_keywords(fetcher)
    search = fetcher.search
    etas: list[int] = []

    async def spying(keyword, sort, time_range, ctx):
        if keyword == "b":
            async with db.sessionmaker() as session:
                task = await session.get(CollectionTask, 1)
                assert task is not None
                etas.append(task.progress["eta_seconds"])
        async for page in search(keyword, sort, time_range, ctx):
            yield page

    fetcher.search = spying
    try:
        await worker.execute(service, "bili", 1)
        assert len(etas) == 1 and etas[0] > 0
    finally:
        await db.close()


async def test_pause_cancels_current_item_and_resume(tmp_path: Path) -> None:
    section = PlatformSection(platform="bili", targets=["a"], quantity=0, depth=Depth())
    db, service, fetcher, _ = await setup(tmp_path, section, ["a"])
    try:
        fetcher.block = True
        active = asyncio.create_task(worker.execute(service, "bili", 1))
        service._active["bili"] = active
        service._active_ids["bili"] = 1
        await fetcher.entered.wait()
        assert (await service.pause(1)).status == "paused"
        async with db.sessionmaker() as session:
            item = await session.scalar(select(TaskItem))
            assert item is not None and item.state == "pending"
        service._active.clear()
        service._active_ids.clear()
        await service.resume(1)
        fetcher.block = False
        await worker.execute(service, "bili", 1)
        assert fetcher.calls == ["a", "a"]
    finally:
        await db.close()


async def test_page_changed_blocks_until_upgrade(tmp_path: Path) -> None:
    section = PlatformSection(platform="bili", keywords=["a"], quantity=1, depth=Depth())
    db, service, fetcher, _ = await setup(tmp_path, section)
    try:
        fetcher.pages = {
            "a": [
                SearchPage(contents=[], has_more=False, report=ParseReport(nonempty_response=True))
            ]
        }
        await worker.execute(service, "bili", 1)
        async with db.sessionmaker.begin() as session:
            task = await session.get(CollectionTask, 1)
            status = await service.platform_view(session, "bili")
            assert task is not None and task.reason == "page_changed"
            assert status.wait_reason == "page_changed"
        service.runtime = None
        service.app_version = "b"
        await service.start()
        async with db.sessionmaker.begin() as session:
            assert (await service.platform_view(session, "bili")).state == "normal"
    finally:
        await db.close()


async def test_quota_requeues_then_next_day_continues(tmp_path: Path) -> None:
    section = PlatformSection(platform="bili", targets=["a", "b"], quantity=0, depth=Depth())
    db, service, fetcher, clock = await setup(tmp_path, section, ["a", "b"])
    try:
        async with db.sessionmaker.begin() as session:
            await set_setting(session, "collect.rate_limits.bili", {"daily_quota": 1})
        await worker.execute(service, "bili", 1)
        async with db.sessionmaker.begin() as session:
            task = await session.get(CollectionTask, 1)
            assert task is not None and task.status == "queued"
            assert (await service.platform_view(session, "bili")).wait_reason == "quota_exhausted"
        clock.now = 86400000
        async with db.sessionmaker.begin() as session:
            assert (await service.platform_view(session, "bili")).wait_reason is None
        await worker.execute(service, "bili", 1)
        async with db.sessionmaker() as session:
            task = await session.get(CollectionTask, 1)
            assert task is not None and task.status == "completed"
            assert task.progress["last_log"].startswith("已采 b：")
        assert fetcher.calls == ["a", "b"]
    finally:
        await db.close()


async def test_task_log_records_how_the_page_was_opened(tmp_path: Path) -> None:
    section = PlatformSection(platform="bili", targets=["a"], quantity=0, depth=Depth())
    db, service, fetcher, _ = await setup(tmp_path, section, ["a"])
    fetcher.route = "结果页卡片"
    try:
        await worker.execute(service, "bili", 1)
        async with db.sessionmaker() as session:
            task = await session.get(CollectionTask, 1)
            assert task is not None
            assert task.progress["last_log"] == "已采 a：评论 0 条，字幕 0 份（结果页卡片）"
    finally:
        await db.close()


async def test_two_platform_workers_do_not_block_each_other(tmp_path: Path) -> None:
    section = PlatformSection(platform="bili", targets=["a"], quantity=0, depth=Depth())
    db, service, bili, clock = await setup(tmp_path, section, ["a"])
    xhs = Fetcher()
    bili.block = xhs.block = True

    class Both:
        platforms = frozenset({"bili", "xhs"})

        def fetcher(self, platform):
            return bili if platform == "bili" else xhs

    service.runtime = cast(PlatformRuntime, Both())
    try:
        section_xhs = PlatformSection(platform="xhs", targets=["b"], quantity=0, depth=Depth())
        snapshot = TaskSnapshot(
            plan_title="测试",
            dataset_id=1,
            dataset_name="测试",
            section=section_xhs.model_dump(),
            confirmed_at=clock.now,
            rate_limits=DEFAULT_RATE_LIMITS["xhs"],
        )
        async with db.sessionmaker.begin() as session:
            session.add(
                CollectionTask(
                    id=2,
                    dataset_id=1,
                    platform="xhs",
                    status="queued",
                    queue_key=1,
                    snapshot=snapshot.model_dump(mode="json"),
                    progress=TaskProgress().model_dump(),
                    created_at=clock.now,
                    updated_at=clock.now,
                )
            )
            await session.flush()
            session.add(
                TaskItem(
                    task_id=2,
                    platform_id="b",
                    ref=ContentRef(platform="xhs", platform_id="b", url="b").model_dump(),
                    source="target",
                    seq=1,
                    state="pending",
                )
            )
        await service.start()
        await asyncio.gather(wait_ready(bili.entered), wait_ready(xhs.entered))
        assert bili.calls == ["a"] and xhs.calls == ["b"]
        await service.stop()
        async with db.sessionmaker() as session:
            tasks = list(await session.scalars(select(CollectionTask).order_by(CollectionTask.id)))
            assert [(task.status, task.reason) for task in tasks] == [
                ("paused", "app_restart"),
                ("paused", "app_restart"),
            ]
    finally:
        await service.stop()
        await db.close()


async def test_sleep_until_deadline_or_wakeup(tmp_path: Path) -> None:
    section = PlatformSection(platform="bili", targets=["a"], quantity=0, depth=Depth())
    db, service, _, _ = await setup(tmp_path, section)

    class ManualClock:
        def __init__(self) -> None:
            self.now = 0
            self.waiting = asyncio.Event()
            self.release = asyncio.Event()

        def now_ms(self) -> int:
            return self.now

        async def sleep(self, seconds: float) -> None:
            self.waiting.set()
            await self.release.wait()

    clock = ManualClock()
    service.clock = clock
    service._wake_events["bili"] = asyncio.Event()
    try:
        waiting = asyncio.create_task(worker.sleep_or_wake(service, "bili", 1000))
        await clock.waiting.wait()
        assert not waiting.done()
        service.wake("bili")
        await waiting
        clock.waiting.clear()
        waiting = asyncio.create_task(worker.sleep_or_wake(service, "bili", 1000))
        await clock.waiting.wait()
        clock.now = 1000
        clock.release.set()
        await waiting
    finally:
        await db.close()


async def test_time_filter_and_satisfied_depth(tmp_path: Path) -> None:
    section = PlatformSection(
        platform="bili",
        keywords=["a"],
        quantity=2,
        depth=Depth(),
        time_range=TimeRange(start="1970-01-01", end="1970-01-01"),
    )
    db, service, fetcher, _ = await setup(tmp_path, section)
    try:
        existing = record("existing").model_copy(
            update={"completeness": "detail", "published_at": 100000}
        )
        async with db.sessionmaker.begin() as session:
            await repo_content.upsert_contents(session, [existing], None, 1)
        inside = record("existing").model_copy(update={"published_at": 100000})
        outside = record("outside").model_copy(update={"published_at": 86400000})
        fetcher.pages = {
            "a": [
                SearchPage(contents=[inside, outside], has_more=False, report=ParseReport(items=2))
            ]
        }
        await worker.execute(service, "bili", 1)
        async with db.sessionmaker() as session:
            items = list(await session.scalars(select(TaskItem)))
            task = await session.get(CollectionTask, 1)
            assert len(items) == 1 and items[0].skip_reason == "already_satisfied"
            assert task is not None and task.progress["quota_counted"] == 0
            assert fetcher.calls == []
    finally:
        await db.close()


async def test_same_platform_fifo_waits_for_active_task(tmp_path: Path) -> None:
    section = PlatformSection(platform="bili", targets=["a"], quantity=0, depth=Depth())
    db, service, fetcher, clock = await setup(tmp_path, section, ["a"])
    fetcher.block = True
    try:
        async with db.sessionmaker.begin() as session:
            first = await session.get(CollectionTask, 1)
            assert first is not None
            session.add(
                CollectionTask(
                    id=2,
                    dataset_id=1,
                    platform="bili",
                    status="queued",
                    queue_key=2,
                    snapshot=first.snapshot,
                    progress=TaskProgress().model_dump(),
                    created_at=clock.now,
                    updated_at=clock.now,
                )
            )
            await session.flush()
            session.add(
                TaskItem(
                    task_id=2,
                    platform_id="b",
                    ref=ContentRef(platform="bili", platform_id="b", url="b").model_dump(),
                    source="target",
                    seq=1,
                    state="pending",
                )
            )
        await service.start()
        await wait_ready(fetcher.entered)
        assert fetcher.calls == ["a"]
        async with db.sessionmaker.begin() as session:
            tasks = await service.task_views(session)
            assert tasks[1].wait_reason == "queue"
        fetcher.entered.clear()
        await service.stop_tasks(task_id=1)
        await wait_ready(fetcher.entered)
        assert fetcher.calls == ["a", "b"]
    finally:
        await service.stop()
        await db.close()


async def test_search_transient_error_retries_same_page(tmp_path: Path) -> None:
    section = PlatformSection(
        platform="bili", keywords=["a"], quantity=1, depth=Depth(detail=False)
    )
    db, service, fetcher, clock = await setup(tmp_path, section)
    attempts = 0

    async def search(keyword, sort, time_range, ctx):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TransientError()
        yield SearchPage(contents=[record("a")], has_more=False, report=ParseReport(items=1))

    fetcher.search = search
    try:
        await worker.execute(service, "bili", 1)
        async with db.sessionmaker() as session:
            task = await session.get(CollectionTask, 1)
            assert task is not None and task.status == "completed"
        assert attempts == 3 and clock.delays == [5, 15]
    finally:
        await db.close()


async def test_worker_automatically_resumes_at_midnight(tmp_path: Path) -> None:
    section = PlatformSection(platform="bili", targets=["a"], quantity=0, depth=Depth())
    db, service, fetcher, _ = await setup(tmp_path, section, ["a"])

    class ManualClock:
        def __init__(self) -> None:
            self.now = 100000
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.deadline = 0

        def now_ms(self) -> int:
            return self.now

        async def sleep(self, seconds: float) -> None:
            self.deadline = self.now + int(seconds * 1000)
            self.started.set()
            await self.release.wait()

    clock = ManualClock()
    service.clock = clock
    fetcher.block = True
    try:
        async with db.sessionmaker.begin() as session:
            await set_setting(session, "collect.rate_limits.bili", {"daily_quota": 1})
            session.add(
                PlatformState(
                    platform="bili",
                    state="normal",
                    quota_day="1970-01-01",
                    quota_used=1,
                    updated_at=clock.now,
                )
            )
        await service.start()
        await wait_ready(clock.started)
        assert clock.deadline == 86400000 and fetcher.calls == []
        clock.now = clock.deadline
        clock.release.set()
        await wait_ready(fetcher.entered)
        assert fetcher.calls == ["a"]
    finally:
        await service.stop()
        await db.close()


async def test_resume_preserves_completed_and_restarts_inflight_item(tmp_path: Path) -> None:
    section = PlatformSection(platform="bili", targets=["a", "b"], quantity=0, depth=Depth())
    db, service, fetcher, _ = await setup(tmp_path, section, ["a", "b"])
    fetcher.block_ids.add("b")
    try:
        await service.start()
        for _ in range(10):
            fetcher.entered.clear()
            if fetcher.calls == ["a", "b"]:
                break
            await wait_ready(fetcher.entered)
        assert fetcher.calls == ["a", "b"]
        await service.pause(1)
        async with db.sessionmaker() as session:
            items = list(await session.scalars(select(TaskItem).order_by(TaskItem.seq)))
            assert [item.state for item in items] == ["done", "pending"]
        fetcher.block_ids.clear()
        await service.resume(1)
        for _ in range(10):
            fetcher.entered.clear()
            if fetcher.calls == ["a", "b", "b"]:
                break
            await wait_ready(fetcher.entered)
        assert fetcher.calls == ["a", "b", "b"]
    finally:
        await service.stop()
        await db.close()


async def test_worker_survives_scheduling_error(tmp_path: Path, monkeypatch) -> None:
    section = PlatformSection(platform="bili", targets=["a"], quantity=0, depth=Depth())
    db, service, fetcher, _ = await setup(tmp_path, section, ["a"])
    original = worker.platform_state.view
    calls = 0

    async def flaky_view(*args, **kwargs):
        # 第 1 次是 start() 里的，第 2 次是 worker 的第一轮调度。
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("读库失败")
        return await original(*args, **kwargs)

    monkeypatch.setattr(worker.platform_state, "view", flaky_view)
    try:
        await service.start()
        await wait_ready(fetcher.entered)
        assert fetcher.calls == ["a"]
    finally:
        await service.stop()
        await db.close()
