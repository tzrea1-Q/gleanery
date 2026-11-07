import json
from typing import Any

from pydantic_ai import ApprovalRequired, RunContext

from gleanery.agent.deps import AgentDeps
from gleanery.api.plans import plan_out
from gleanery.collect.plan import PlanBody
from gleanery.collect.plan_check import check
from gleanery.platforms.types import Platform
from gleanery.store import repo_datasets, repo_plans
from gleanery.store.models import Dataset


def error(code: str, message: str, hint: str | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "hint": hint}}


def conflict(exc: repo_plans.VersionConflict) -> dict[str, Any]:
    return error(
        "VERSION_CONFLICT",
        "计划版本冲突",
        json.dumps({"version": exc.current.version, "plan": exc.current.body}, ensure_ascii=False),
    )


def task_result(view: Any) -> dict[str, Any]:
    result = view.model_dump(mode="json", exclude={"snapshot"})
    progress = result["progress"]
    # 2026-11-02 冒烟：模型把 comments 当成一级评论数、把 keyword 当成全部内容的来源。
    # keyword 只是正在搜的词，搜索结束后不再给；评论数改成带说明的键名。
    if progress.get("phase") != "search":
        progress.pop("keyword", None)
    progress["comments_including_replies"] = progress.pop("comments", 0)
    log = progress.pop("last_log", None)
    if log is not None:
        result["untrusted"] = {"last_log": log}
    return result


async def propose_collection_plan(ctx: RunContext[AgentDeps], plan: PlanBody) -> dict[str, Any]:
    """起草采集计划并返回校验结果。起草后请用户在卡片上检查，不要在同一轮调用 start_collection。"""
    async with ctx.deps.sessionmaker() as session:
        now = ctx.deps.clock.now_ms()
        draft = await repo_plans.create_draft(session, ctx.deps.conversation_id, plan, now)
        out = await plan_out(session, draft, ctx.deps.collect, now)
        await session.commit()
        ctx.deps.events.publish("plan.updated", {"plan_id": draft.id})
        return {
            "plan_id": draft.id,
            "version": draft.version,
            "issues": [issue.model_dump() for issue in out.issues],
            "estimate_seconds": out.estimate_seconds,
            "platforms": [section.platform for section in plan.sections],
        }


async def get_collection_plan(ctx: RunContext[AgentDeps], plan_id: int) -> dict[str, Any]:
    """读取最新采集计划。"""
    async with ctx.deps.sessionmaker() as session:
        plan = await repo_plans.get(session, plan_id)
        if plan is None:
            return error("PLAN_NOT_FOUND", "计划不存在")
        out = await plan_out(session, plan, ctx.deps.collect, ctx.deps.clock.now_ms())
        return {
            "plan_id": out.id,
            "status": out.status,
            "version": out.version,
            "plan": out.body.model_dump(mode="json"),
            "issues": [issue.model_dump() for issue in out.issues],
            "estimate_seconds": out.estimate_seconds,
        }


async def update_collection_plan(
    ctx: RunContext[AgentDeps], plan_id: int, base_version: int, plan: PlanBody
) -> dict[str, Any]:
    """按版本替换采集计划草稿。"""
    async with ctx.deps.sessionmaker() as session:
        try:
            draft = await repo_plans.replace(
                session, plan_id, base_version, plan, ctx.deps.clock.now_ms()
            )
        except repo_plans.PlanLocked:
            return error("PLAN_LOCKED", "计划已确认")
        except repo_plans.VersionConflict as exc:
            return conflict(exc)
        if draft is None:
            return error("PLAN_NOT_FOUND", "计划不存在")
        await session.commit()
    ctx.deps.events.publish("plan.updated", {"plan_id": plan_id})
    return await get_collection_plan(ctx, plan_id)


async def start_collection(ctx: RunContext[AgentDeps], plan_id: int) -> dict[str, Any]:
    """校验并请求用户批准，批准后启动采集。只在用户明确说开始之后调用。"""
    async with ctx.deps.sessionmaker() as session:
        plan = await repo_plans.get(session, plan_id)
        if plan is None:
            return error("PLAN_NOT_FOUND", "计划不存在")
        if plan.status != "draft":
            return error("PLAN_LOCKED", "计划已确认")
        now = ctx.deps.clock.now_ms()
        body = PlanBody.model_validate(plan.body)
        issues, resolved = await check(session, body, ctx.deps.collect, now)
        invalid = next((issue for issue in issues if issue.severity == "error"), None)
        if invalid:
            return error(invalid.code, invalid.message)
        if not ctx.tool_call_approved:
            raise ApprovalRequired(metadata={"plan_id": plan_id, "version": plan.version})
        if body.target_dataset_id is None:
            dataset = await repo_datasets.create_dataset(
                session,
                body.new_dataset_name or body.title,
                body.new_dataset_description or "",
                ctx.deps.conversation_id,
                now,
            )
        else:
            dataset = await session.get(Dataset, body.target_dataset_id)
            if dataset is None:
                return error("DATASET_NOT_FOUND", "数据集不存在")
        try:
            await repo_plans.confirm(session, plan, dataset.id, now)
        except repo_plans.PlanLocked:
            return error("PLAN_LOCKED", "计划已确认")
        except repo_plans.VersionConflict as exc:
            return conflict(exc)
        task_ids = await ctx.deps.collect.enqueue_plan(
            session, plan, dataset, body.sections, resolved, now
        )
        views = await ctx.deps.collect.task_views(session, task_ids=task_ids)
        dataset_id = dataset.id
        await session.commit()
    for section in body.sections:
        ctx.deps.collect.wake(section.platform)
    ctx.deps.events.publish("plan.updated", {"plan_id": plan_id})
    return {
        "plan_id": plan_id,
        "dataset_id": dataset_id,
        "tasks": [
            {
                "task_id": view.id,
                "platform": view.platform,
                "status": view.status,
                "queue_position": view.queue_position,
                "wait_reason": view.wait_reason,
                "wait_until": view.wait_until,
            }
            for view in views
        ],
    }


async def get_collection_status(
    ctx: RunContext[AgentDeps], plan_id: int | None = None, task_id: int | None = None
) -> dict[str, Any]:
    """查看计划或任务的采集进度。"""
    if (plan_id is None) == (task_id is None):
        return error("INVALID_REQUEST", "请指定一个计划或任务")
    async with ctx.deps.sessionmaker() as session:
        views = await ctx.deps.collect.task_views(
            session, plan_id=plan_id, task_ids=[task_id] if task_id is not None else None
        )
        return {"tasks": [task_result(view) for view in views]}


async def stop_collection(
    ctx: RunContext[AgentDeps], plan_id: int | None = None, task_id: int | None = None
) -> dict[str, Any]:
    """停止计划或任务中未结束的采集。

    只在用户明确要求停止采集时调用，不要为了完成别的操作（比如删除数据集）自行停止。
    """
    if (plan_id is None) == (task_id is None):
        return error("INVALID_REQUEST", "请指定一个计划或任务")
    views = await ctx.deps.collect.stop_tasks(task_id=task_id, plan_id=plan_id)
    return {"tasks": [task_result(view) for view in views]}


async def get_platform_status(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
    """查看平台状态，不启动浏览器。"""
    async with ctx.deps.sessionmaker() as session:
        platforms: tuple[Platform, ...] = ("bili", "xhs")
        return {
            "platforms": [
                (await ctx.deps.collect.platform_view(session, platform)).model_dump(mode="json")
                for platform in platforms
            ]
        }


async def list_datasets(
    ctx: RunContext[AgentDeps], keyword: str | None = None, platform: Platform | None = None
) -> dict[str, Any]:
    """列出数据集，可按名称或平台筛选。"""
    async with ctx.deps.sessionmaker() as session:
        datasets = await repo_datasets.list_all(session)
        matches = [
            item.model_dump(mode="json")
            for item in datasets
            if (not keyword or keyword.casefold() in item.name.casefold())
            and (not platform or item.counts.get(platform, 0) > 0)
        ]
        return {"datasets": matches[:50], "total": len(matches)}
