"""设置里的"删除所有采集数据"。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.deps import get_collect, get_events, get_session
from gleanery.api.errors import ApiError, ErrorBody
from gleanery.api.schemas_data import ClearRequest, DataImpact
from gleanery.collect.service import CollectService
from gleanery.events import EventBus
from gleanery.store import cleanup

router = APIRouter(prefix="/api/data", tags=["data"])
_409: dict[int | str, dict[str, Any]] = {409: {"model": ErrorBody}}


@router.get("/impact", response_model=DataImpact)
async def data_impact(session: Annotated[AsyncSession, Depends(get_session)]) -> DataImpact:
    return await cleanup.impact_of_all(session)


@router.post("/clear", response_model=DataImpact, responses=_409)
async def clear_data(
    body: ClearRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    events: Annotated[EventBus, Depends(get_events)],
    collect: Annotated[CollectService, Depends(get_collect)],
    request: Request,
) -> DataImpact:
    """返回删除前的条数。有非终态任务且 `stop_active` 为假时 409 `DATASET_HAS_ACTIVE_TASKS`。"""
    impact = await cleanup.impact_of_all(session)
    if impact.active_task_ids and body.stop_active:
        await session.rollback()
        for task_id in impact.active_task_ids:
            await collect.stop_tasks(task_id=task_id)
    try:
        result = await cleanup.delete_all_collected(session)
    except cleanup.HasActiveTasks as exc:
        raise ApiError(
            409, "DATASET_HAS_ACTIVE_TASKS", "有未结束的采集任务", str(exc.task_ids)
        ) from exc
    await session.commit()
    events.publish("data.cleared", {})
    await cleanup.vacuum(request.app.state.db)
    return result
