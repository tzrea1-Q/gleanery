"""采集设置与风控事件。"""

from typing import Annotated, cast

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.deps import get_session
from gleanery.api.errors import ApiError, ErrorBody
from gleanery.api.schemas_collect import (
    CollectSettings,
    CollectSettingsUpdate,
    PlatformRateSettings,
    RiskEventOut,
)
from gleanery.collect.settings import (
    RateTooLoose,
    load_rate_limits,
    reset_rate_limits,
    save_rate_limits,
    set_warmup_enabled,
    warmup_enabled,
)
from gleanery.collect.types import DEFAULT_RATE_LIMITS
from gleanery.platforms.types import Platform
from gleanery.store.models import RiskEvent

router = APIRouter(prefix="/api", tags=["collect-settings"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/collect-settings", response_model=CollectSettings)
async def get_settings(session: Session) -> CollectSettings:
    return CollectSettings(
        warmup_enabled=await warmup_enabled(session),
        platforms={
            platform: PlatformRateSettings(
                current=await load_rate_limits(session, platform), defaults=defaults
            )
            for platform, defaults in DEFAULT_RATE_LIMITS.items()
        },
    )


@router.patch(
    "/collect-settings",
    response_model=CollectSettings,
    responses={422: {"model": ErrorBody, "description": "RATE_TOO_LOOSE：放宽到下限以下"}},
)
async def update_settings(body: CollectSettingsUpdate, session: Session) -> CollectSettings:
    """只对之后开始的任务生效。"""
    try:
        for name, update in (body.platforms or {}).items():
            if name not in DEFAULT_RATE_LIMITS:
                raise ApiError(422, "PLATFORM_UNSUPPORTED", "平台不存在")
            await save_rate_limits(
                session, cast(Platform, name), update.model_dump(exclude_none=True)
            )
        if body.warmup_enabled is not None:
            await set_warmup_enabled(session, body.warmup_enabled)
        await session.commit()
    except RateTooLoose as error:
        await session.rollback()
        raise ApiError(422, "RATE_TOO_LOOSE", str(error)) from error
    return await get_settings(session)


@router.post("/collect-settings/{platform}/reset", response_model=CollectSettings)
async def reset_settings(platform: Platform, session: Session) -> CollectSettings:
    await reset_rate_limits(session, platform)
    await session.commit()
    return await get_settings(session)


@router.get("/risk-events", response_model=list[RiskEventOut])
async def list_risk_events(
    session: Session,
    platform: Platform | None = None,
    limit: int = 100,
) -> list[RiskEventOut]:
    if limit < 1:
        raise ApiError(422, "INVALID_LIMIT", "数量必须大于零")
    query = select(RiskEvent).order_by(RiskEvent.at.desc(), RiskEvent.id.desc()).limit(limit)
    if platform is not None:
        query = query.where(RiskEvent.platform == platform)
    rows = (await session.scalars(query)).all()
    return [RiskEventOut.model_validate(row, from_attributes=True) for row in rows]
