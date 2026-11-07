from pathlib import Path

from gleanery.collect.estimate import estimate_task_seconds
from gleanery.collect.plan import DEFAULT_DEPTH, PlatformSection
from gleanery.collect.settings import load_rate_limits, rate_limits_key, warmup_enabled
from gleanery.collect.types import DEFAULT_RATE_LIMITS
from gleanery.platforms.types import Depth
from gleanery.store import open_database
from gleanery.store.repo_settings import set_setting


async def test_rate_limits_overlay_defaults(tmp_path: Path) -> None:
    database = await open_database(tmp_path)
    try:
        async with database.sessionmaker() as session:
            assert await load_rate_limits(session, "bili") == DEFAULT_RATE_LIMITS["bili"]
            assert await warmup_enabled(session) is True
            await set_setting(session, rate_limits_key("bili"), {"page_interval": [5, 9]})
            limits = await load_rate_limits(session, "bili")
            assert limits.page_interval == (5, 9)
            assert limits.daily_quota == DEFAULT_RATE_LIMITS["bili"].daily_quota
    finally:
        await database.close()


def test_estimate() -> None:
    limits = DEFAULT_RATE_LIMITS["bili"]
    summary = PlatformSection(
        platform="bili", keywords=["咖啡"], depth=Depth(detail=False), quantity=40
    )
    # 只要摘要：2 页搜索，每页平均 5.5 秒。
    assert estimate_task_seconds(summary, limits) == 11
    full = PlatformSection(
        platform="bili", keywords=["咖啡"], depth=DEFAULT_DEPTH["bili"], quantity=100
    )
    # 100 条：5 页搜索 + 每条（5.5 + 3 + 5 页评论 × 3.5）+ 2 次长休息。
    assert estimate_task_seconds(full, limits) == round(5 * 5.5 + 100 * 26 + 2 * 120)
