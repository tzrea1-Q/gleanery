"""采集计划：工作区读取与编辑草稿（ADR-0002）。确认只走 Agent 工具 `start_collection` 的审批。"""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.deps import get_collect, get_deps, get_events, get_session
from gleanery.api.errors import ApiError, ErrorBody
from gleanery.api.schemas_collect import PlanOut, PlanPatch
from gleanery.collect.plan import PlanBody
from gleanery.collect.plan_check import check, estimates
from gleanery.collect.service import CollectService
from gleanery.deps import AppDeps
from gleanery.events import EventBus
from gleanery.store import repo_plans
from gleanery.store.models import CollectionPlan, CollectionTask

router = APIRouter(prefix="/api/plans", tags=["plans"])
_errors: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorBody},
    409: {
        "model": ErrorBody,
        "description": "PLAN_LOCKED 或 VERSION_CONFLICT（hint 里不带全文，前端重新 GET）",
    },
}


async def plan_out(
    session: AsyncSession, plan: CollectionPlan, collect: CollectService, now: int
) -> PlanOut:
    body = PlanBody.model_validate(plan.body)
    # 校验和提示是开始前看的；确认后任务已建好，等待原因由任务进度显示。
    issues = (await check(session, body, collect, now))[0] if plan.status == "draft" else []
    task_ids = list(
        await session.scalars(
            select(CollectionTask.id)
            .where(CollectionTask.plan_id == plan.id)
            .order_by(CollectionTask.id)
        )
    )
    return PlanOut(
        id=plan.id,
        conversation_id=plan.conversation_id,
        status=cast(Any, plan.status),
        version=plan.version,
        body=body,
        issues=issues,
        estimate_seconds=await estimates(session, body),
        task_ids=task_ids,
        confirmed_at=plan.confirmed_at,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


@router.get("", response_model=list[PlanOut])
async def list_plans(
    conversation_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    collect: Annotated[CollectService, Depends(get_collect)],
    deps: Annotated[AppDeps, Depends(get_deps)],
) -> list[PlanOut]:
    """本对话的全部计划，按创建先后排列；工作区据此找到当前计划。"""
    plans = await session.scalars(
        select(CollectionPlan)
        .where(CollectionPlan.conversation_id == conversation_id)
        .order_by(CollectionPlan.id)
    )
    now = deps.clock.now_ms()
    return [await plan_out(session, plan, collect, now) for plan in plans]


@router.get("/{plan_id}", response_model=PlanOut, responses=_errors)
async def get_plan(
    plan_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    collect: Annotated[CollectService, Depends(get_collect)],
    deps: Annotated[AppDeps, Depends(get_deps)],
) -> PlanOut:
    plan = await repo_plans.get(session, plan_id)
    if plan is None:
        raise ApiError(404, "PLAN_NOT_FOUND", "计划不存在")
    return await plan_out(session, plan, collect, deps.clock.now_ms())


@router.patch("/{plan_id}", response_model=PlanOut, responses=_errors)
async def patch_plan(
    plan_id: int,
    body: PlanPatch,
    session: Annotated[AsyncSession, Depends(get_session)],
    collect: Annotated[CollectService, Depends(get_collect)],
    deps: Annotated[AppDeps, Depends(get_deps)],
    events: Annotated[EventBus, Depends(get_events)],
) -> PlanOut:
    """整份替换草稿，版本号加 1，发布 plan.updated。"""
    now = deps.clock.now_ms()
    try:
        plan = await repo_plans.replace(session, plan_id, body.base_version, body.body, now)
    except repo_plans.PlanLocked as exc:
        raise ApiError(409, "PLAN_LOCKED", "计划已确认") from exc
    except repo_plans.VersionConflict as exc:
        raise ApiError(
            409, "VERSION_CONFLICT", "计划版本冲突", f"当前版本：{exc.current.version}"
        ) from exc
    if plan is None:
        raise ApiError(404, "PLAN_NOT_FOUND", "计划不存在")
    result = await plan_out(session, plan, collect, now)
    await session.commit()
    events.publish("plan.updated", {"plan_id": plan_id})
    return result
