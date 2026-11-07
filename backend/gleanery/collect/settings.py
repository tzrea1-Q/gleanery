"""采集设置：限速参数的用户覆盖值与预热开关。

存在 `setting` 表：`collect.rate_limits.<platform>` 只存与默认值不同的字段，
`collect.warmup_enabled` 缺省为开。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.collect.types import DEFAULT_RATE_LIMITS, RateLimits
from gleanery.platforms.types import Platform
from gleanery.store.models import Setting
from gleanery.store.repo_settings import get_setting, set_setting

WARMUP_KEY = "collect.warmup_enabled"


def rate_limits_key(platform: Platform) -> str:
    return f"collect.rate_limits.{platform}"


async def load_rate_limits(session: AsyncSession, platform: Platform) -> RateLimits:
    """当前生效的限速参数：默认值叠加用户覆盖值。"""
    overrides: dict[str, Any] = await get_setting(session, rate_limits_key(platform), {}) or {}
    return RateLimits.model_validate(DEFAULT_RATE_LIMITS[platform].model_dump() | overrides)


async def warmup_enabled(session: AsyncSession) -> bool:
    return bool(await get_setting(session, WARMUP_KEY, True))


class RateTooLoose(ValueError):
    """放宽到下限以下，或区间下界大于上界。REST 返回 422 `RATE_TOO_LOOSE`。"""


async def save_rate_limits(
    session: AsyncSession, platform: Platform, update: dict[str, Any]
) -> RateLimits:
    """校验并合并覆盖值，返回新的生效值。只对之后开始的任务生效。不 commit。"""
    defaults = DEFAULT_RATE_LIMITS[platform]
    current = await load_rate_limits(session, platform)
    values = current.model_dump() | update
    # 放宽的下限是默认值下界的一半；页面间隔的一半即 page_interval_floor。
    floors = {
        "page_interval": defaults.page_interval_floor,
        "comment_page_interval": defaults.comment_page_interval[0] / 2,
    }
    for key, floor in floors.items():
        low, high = values[key]
        if low < floor:
            raise RateTooLoose(f"间隔下界不能低于 {floor:g} 秒")
        if low > high:
            raise RateTooLoose("间隔区间的下界不能大于上界")
    result = RateLimits.model_validate(values)
    baseline = defaults.model_dump()
    overrides = {key: value for key, value in result.model_dump().items() if value != baseline[key]}
    await set_setting(session, rate_limits_key(platform), overrides)
    return result


async def reset_rate_limits(session: AsyncSession, platform: Platform) -> RateLimits:
    """删掉该平台的覆盖值。不 commit。"""
    await session.execute(delete(Setting).where(Setting.key == rate_limits_key(platform)))
    return DEFAULT_RATE_LIMITS[platform].model_copy()


async def set_warmup_enabled(session: AsyncSession, enabled: bool) -> None:
    await set_setting(session, WARMUP_KEY, enabled)
