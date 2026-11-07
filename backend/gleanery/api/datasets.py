"""数据集：列表、详情、浏览与管理。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.deps import get_collect, get_deps, get_events, get_session
from gleanery.api.errors import ApiError, ErrorBody
from gleanery.api.schemas_collect import ContentPage, DatasetOut
from gleanery.api.schemas_data import (
    ContentIds,
    DatasetUpdate,
    DeleteImpact,
    LocateOffset,
    RemoveImpact,
)
from gleanery.collect.service import CollectService
from gleanery.deps import AppDeps
from gleanery.events import EventBus
from gleanery.query.browse import content_offset
from gleanery.query.filters import ContentFilter, ContentSort
from gleanery.store import cleanup
from gleanery.store import repo_datasets as repo
from gleanery.store.models import Dataset

router = APIRouter(prefix="/api/datasets", tags=["datasets"])
_404: dict[int | str, dict[str, Any]] = {404: {"model": ErrorBody}}
_409: dict[int | str, dict[str, Any]] = {404: {"model": ErrorBody}, 409: {"model": ErrorBody}}


@router.get("", response_model=list[DatasetOut])
async def list_datasets(session: Annotated[AsyncSession, Depends(get_session)]) -> list[DatasetOut]:
    return await repo.list_all(session)


@router.get("/{dataset_id}", response_model=DatasetOut, responses=_404)
async def get_dataset(
    dataset_id: int, session: Annotated[AsyncSession, Depends(get_session)]
) -> DatasetOut:
    dataset = await repo.get(session, dataset_id)
    if dataset is None:
        raise ApiError(404, "DATASET_NOT_FOUND", "数据集不存在")
    return dataset


# ---------- 浏览 ----------


@router.get("/{dataset_id}/contents", response_model=ContentPage, responses=_404)
async def list_contents(
    dataset_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    deps: Annotated[AppDeps, Depends(get_deps)],
    filter: Annotated[ContentFilter, Query()],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort: ContentSort = "added_desc",
) -> ContentPage:
    """按筛选与排序分页。"""
    await get_dataset(dataset_id, session)
    return await repo.contents_page(session, dataset_id, limit, offset, filter, sort, deps.tz)


@router.get("/{dataset_id}/contents/locate", response_model=LocateOffset, responses=_404)
async def locate_content(
    dataset_id: int,
    content_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    filter: Annotated[ContentFilter, Query()],
    deps: Annotated[AppDeps, Depends(get_deps)],
    sort: ContentSort = "added_desc",
) -> LocateOffset:
    """这条内容在当前筛选与排序下的行号。"""
    await get_dataset(dataset_id, session)
    return LocateOffset(
        offset=await content_offset(session, dataset_id, content_id, filter, sort, deps.tz)
    )


# ---------- 管理 ----------


@router.patch("/{dataset_id}", response_model=DatasetOut, responses=_404)
async def update_dataset(
    dataset_id: int,
    body: DatasetUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    events: Annotated[EventBus, Depends(get_events)],
) -> DatasetOut:
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None:
        raise ApiError(404, "DATASET_NOT_FOUND", "数据集不存在")
    if body.name is not None:
        if not body.name.strip():
            raise ApiError(422, "INVALID_REQUEST", "名称不能为空")
        dataset.name = body.name
    if body.description is not None:
        dataset.description = body.description
    await session.commit()
    events.publish("dataset.updated", {"dataset_id": dataset_id})
    return await get_dataset(dataset_id, session)


@router.get("/{dataset_id}/delete-impact", response_model=DeleteImpact, responses=_404)
async def delete_impact(
    dataset_id: int, session: Annotated[AsyncSession, Depends(get_session)]
) -> DeleteImpact:
    impact = await cleanup.impact_of_delete(session, dataset_id)
    if impact is None:
        raise ApiError(404, "DATASET_NOT_FOUND", "数据集不存在")
    return impact


@router.delete("/{dataset_id}", response_model=DeleteImpact, responses=_409)
async def delete_dataset(
    dataset_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    events: Annotated[EventBus, Depends(get_events)],
    collect: Annotated[CollectService, Depends(get_collect)],
    request: Request,
    stop_active: bool = False,
) -> DeleteImpact:
    """有非终态任务且 `stop_active` 为假时 409 `DATASET_HAS_ACTIVE_TASKS`。"""
    impact = await delete_impact(dataset_id, session)
    if impact.active_task_ids and stop_active:
        await session.rollback()
        for task_id in impact.active_task_ids:
            await collect.stop_tasks(task_id=task_id)
    try:
        result = await cleanup.delete_dataset(session, dataset_id)
    except cleanup.HasActiveTasks as exc:
        raise ApiError(
            409, "DATASET_HAS_ACTIVE_TASKS", "数据集有未结束的采集任务", str(exc.task_ids)
        ) from exc
    if result is None:
        raise ApiError(404, "DATASET_NOT_FOUND", "数据集不存在")
    await session.commit()
    events.publish("dataset.deleted", {"dataset_id": dataset_id})
    await cleanup.vacuum(request.app.state.db)
    return result


@router.post("/{dataset_id}/remove-impact", response_model=RemoveImpact, responses=_404)
async def remove_impact(
    dataset_id: int, body: ContentIds, session: Annotated[AsyncSession, Depends(get_session)]
) -> RemoveImpact:
    impact = await cleanup.impact_of_remove(session, dataset_id, body.content_ids)
    if impact is None:
        raise ApiError(404, "DATASET_NOT_FOUND", "数据集不存在")
    return impact


@router.post("/{dataset_id}/remove", response_model=RemoveImpact, responses=_404)
async def remove_contents(
    dataset_id: int,
    body: ContentIds,
    session: Annotated[AsyncSession, Depends(get_session)],
    events: Annotated[EventBus, Depends(get_events)],
    request: Request,
) -> RemoveImpact:
    result = await cleanup.remove_from_dataset(session, dataset_id, body.content_ids)
    if result is None:
        raise ApiError(404, "DATASET_NOT_FOUND", "数据集不存在")
    await session.commit()
    events.publish("dataset.updated", {"dataset_id": dataset_id})
    await cleanup.vacuum(request.app.state.db)
    return result
