"""采集任务：列表、详情，以及用户的暂停、继续、停止（继续只能由用户在界面操作）。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.deps import get_collect, get_session
from gleanery.api.errors import ApiError, ErrorBody
from gleanery.api.schemas_collect import TaskOut
from gleanery.collect.service import CollectService, InvalidTransition

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
_errors: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorBody},
    409: {"model": ErrorBody, "description": "INVALID_TRANSITION"},
}


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    session: Annotated[AsyncSession, Depends(get_session)],
    collect: Annotated[CollectService, Depends(get_collect)],
    plan_id: int | None = None,
    conversation_id: int | None = None,
) -> list[TaskOut]:
    return await collect.task_views(session, plan_id=plan_id, conversation_id=conversation_id)


@router.get("/{task_id}", response_model=TaskOut, responses=_errors)
async def get_task(
    task_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    collect: Annotated[CollectService, Depends(get_collect)],
) -> TaskOut:
    tasks = await collect.task_views(session, task_ids=[task_id])
    if not tasks:
        raise ApiError(404, "TASK_NOT_FOUND", "任务不存在")
    return tasks[0]


@router.post("/{task_id}/pause", response_model=TaskOut, responses=_errors)
async def pause_task(
    task_id: int, collect: Annotated[CollectService, Depends(get_collect)]
) -> TaskOut:
    try:
        return await collect.pause(task_id)
    except LookupError as error:
        raise ApiError(404, "TASK_NOT_FOUND", "任务不存在") from error
    except InvalidTransition as error:
        raise ApiError(409, "INVALID_TRANSITION", str(error)) from error


@router.post("/{task_id}/resume", response_model=TaskOut, responses=_errors)
async def resume_task(
    task_id: int, collect: Annotated[CollectService, Depends(get_collect)]
) -> TaskOut:
    """已暂停 → 回到本平台队首排队。风控暂停的继续即"已验证，继续（冷却后恢复）"。"""
    try:
        return await collect.resume(task_id)
    except LookupError as error:
        raise ApiError(404, "TASK_NOT_FOUND", "任务不存在") from error
    except InvalidTransition as error:
        raise ApiError(409, "INVALID_TRANSITION", str(error)) from error


@router.post("/{task_id}/stop", response_model=TaskOut, responses=_errors)
async def stop_task(
    task_id: int, collect: Annotated[CollectService, Depends(get_collect)]
) -> TaskOut:
    try:
        return (await collect.stop_tasks(task_id=task_id))[0]
    except LookupError as error:
        raise ApiError(404, "TASK_NOT_FOUND", "任务不存在") from error
