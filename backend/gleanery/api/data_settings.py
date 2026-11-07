"""原始响应留存与占用空间。"""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.deps import get_deps, get_events, get_session
from gleanery.api.schemas_data import DataSettings, DataSettingsUpdate, PurgeResult, RetentionDays
from gleanery.deps import AppDeps
from gleanery.events import EventBus
from gleanery.store import cleanup, retention
from gleanery.store.db import DB_FILENAME

router = APIRouter(prefix="/api/data-settings", tags=["data-settings"])


@router.get("", response_model=DataSettings)
async def get_data_settings(
    session: Annotated[AsyncSession, Depends(get_session)],
    deps: Annotated[AppDeps, Depends(get_deps)],
) -> DataSettings:
    count, raw_bytes, db_bytes = await retention.usage(session, deps.data_dir / DB_FILENAME)
    return DataSettings(
        raw_retention_days=cast(RetentionDays | None, await retention.retention_days(session)),
        raw_count=count,
        raw_bytes=raw_bytes,
        db_bytes=db_bytes,
    )


@router.patch("", response_model=DataSettings)
async def update_data_settings(
    body: DataSettingsUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    deps: Annotated[AppDeps, Depends(get_deps)],
    events: Annotated[EventBus, Depends(get_events)],
    request: Request,
) -> DataSettings:
    """改完立即按新天数清理一次。"""
    await retention.set_retention_days(session, body.raw_retention_days)
    await retention.purge_expired(session, deps.clock.now_ms(), body.raw_retention_days)
    await session.commit()
    await cleanup.vacuum(request.app.state.db)
    events.publish("data_settings.changed")
    return await get_data_settings(session, deps)


@router.post("/purge-raw", response_model=PurgeResult)
async def purge_raw(
    session: Annotated[AsyncSession, Depends(get_session)],
    events: Annotated[EventBus, Depends(get_events)],
    request: Request,
) -> PurgeResult:
    """清空全部原始响应。"""
    deleted = await retention.purge_all(session)
    await session.commit()
    if deleted:
        await cleanup.vacuum(request.app.state.db)
    events.publish("data_settings.changed")
    return PurgeResult(deleted=deleted)
