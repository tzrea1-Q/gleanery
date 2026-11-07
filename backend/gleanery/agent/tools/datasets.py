"""数据集管理工具。"""

from typing import Any, cast

from pydantic_ai import ApprovalRequired, RunContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from gleanery.agent.deps import AgentDeps
from gleanery.agent.tools import error
from gleanery.collect.plan import IdList
from gleanery.query.filters import ContentFilter, content_conditions
from gleanery.store import cleanup, repo_datasets
from gleanery.store.db import Database
from gleanery.store.models import Content, Dataset, DatasetItem


def _db(ctx: RunContext[AgentDeps]) -> Database:
    return Database(cast(AsyncEngine, ctx.deps.sessionmaker.kw["bind"]), ctx.deps.sessionmaker)


def _active(ids: list[int]) -> dict[str, Any]:
    return error(
        "DATASET_HAS_ACTIVE_TASKS",
        "数据集有未结束的采集任务",
        f"任务 ID：{', '.join(map(str, ids))}。不要自己停止任务；告诉用户可以在左栏"
        "「所有数据集」里删除并选「停止这些任务并删除」，或等采集结束后再删",
    )


async def save_as_dataset(
    ctx: RunContext[AgentDeps],
    name: str,
    description: str,
    content_ids: IdList | None = None,
    source_dataset_id: int | None = None,
    filter: ContentFilter | None = None,
) -> dict[str, Any]:
    """把内容另存为新数据集，直接生效。只新建，不改来源数据集。

    content_ids 和 source_dataset_id 只给一个：已经挑好了具体内容就给 content_ids；
    要把另一个数据集按条件筛出来的内容整批另存，就给 source_dataset_id 和 filter。

    Args:
        name: 新数据集的名字。
        description: 一句话说明这批内容是什么、怎么挑出来的。
        content_ids: 要另存的内容 ID，最多 5000 个。
        source_dataset_id: 来源数据集 ID，和 content_ids 二选一。
        filter: 配合 source_dataset_id 使用的筛选条件，省略则取来源数据集的全部内容。
    """
    if not name.strip():
        return error("INVALID_REQUEST", "名称不能为空")
    if content_ids is not None and source_dataset_id is not None:
        return error(
            "INVALID_REQUEST",
            "content_ids 和 source_dataset_id 只能给一个",
            "已挑好内容就只给 content_ids；按条件整批另存就给 source_dataset_id 和 filter",
        )
    if content_ids is None and source_dataset_id is None:
        return error("INVALID_REQUEST", "要给 content_ids 或 source_dataset_id")
    async with ctx.deps.sessionmaker() as session:
        if content_ids is not None:
            ids = list(dict.fromkeys(content_ids))
            if len(ids) > 5000:
                return error("INVALID_REQUEST", "最多另存 5000 条内容")
            existing = set(
                (await session.scalars(select(Content.id).where(Content.id.in_(ids)))).all()
            )
            missing = [i for i in ids if i not in existing]
            if missing:
                return error("CONTENT_NOT_FOUND", "内容不存在", ", ".join(map(str, missing)))
        else:
            if await session.get(Dataset, source_dataset_id) is None:
                return error("DATASET_NOT_FOUND", "数据集不存在")
            ids = list(
                (
                    await session.scalars(
                        select(Content.id)
                        .join(DatasetItem, DatasetItem.content_id == Content.id)
                        .where(
                            DatasetItem.dataset_id == source_dataset_id,
                            *content_conditions(filter, ctx.deps.tz),
                        )
                        .limit(5001)
                    )
                ).all()
            )
            if len(ids) > 5000:
                return error("INVALID_REQUEST", "最多另存 5000 条内容")
        now = ctx.deps.clock.now_ms()
        dataset = await repo_datasets.create_dataset(
            session, name, description, ctx.deps.conversation_id, now
        )
        await repo_datasets.add_to_dataset(session, dataset.id, ids, None, now)
        dataset_id = dataset.id
        await session.commit()
    ctx.deps.events.publish("dataset.updated", {"dataset_id": dataset_id})
    return {"dataset_id": dataset_id, "name": name, "total": len(ids)}


async def update_dataset(
    ctx: RunContext[AgentDeps],
    dataset_id: int,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """修改数据集的名称或说明，直接生效。

    Args:
        dataset_id: 数据集 ID。
        name: 新名字，不改就省略。
        description: 新说明，不改就省略。
    """
    if name is not None and not name.strip():
        return error("INVALID_REQUEST", "名称不能为空")
    async with ctx.deps.sessionmaker() as session:
        dataset = await session.get(Dataset, dataset_id)
        if dataset is None:
            return error("DATASET_NOT_FOUND", "数据集不存在")
        if name is not None:
            dataset.name = name
        if description is not None:
            dataset.description = description
        result = {
            "dataset_id": dataset_id,
            "name": dataset.name,
            "description": dataset.description,
        }
        await session.commit()
    ctx.deps.events.publish("dataset.updated", {"dataset_id": dataset_id})
    return result


async def remove_from_dataset(
    ctx: RunContext[AgentDeps], dataset_id: int, content_ids: IdList
) -> dict[str, Any]:
    """把内容移出数据集，会弹出审批，用户批准后才执行。只在用户明确要求移出时调用。

    返回里 removed 是移出的条数；recycled_contents、recycled_comments 是因为不再属于
    任何数据集、随之从本地内容库删掉的内容和评论数，为 0 表示没有内容被删掉。

    Args:
        dataset_id: 数据集 ID。
        content_ids: 要移出的内容 ID，1 到 500 个。
    """
    if not content_ids or len(content_ids) > 500:
        return error("INVALID_REQUEST", "请选择 1 至 500 条内容")
    async with ctx.deps.sessionmaker() as session:
        impact = await cleanup.impact_of_remove(session, dataset_id, content_ids)
        if impact is None:
            return error("DATASET_NOT_FOUND", "数据集不存在")
        if not ctx.tool_call_approved:
            raise ApprovalRequired(
                metadata={
                    "dataset_id": dataset_id,
                    "content_ids": content_ids,
                    "impact": impact.model_dump(),
                }
            )
        result = await cleanup.remove_from_dataset(session, dataset_id, content_ids)
        assert result is not None
        await session.commit()
    ctx.deps.events.publish("dataset.updated", {"dataset_id": dataset_id})
    await cleanup.vacuum(_db(ctx))
    return result.model_dump()


async def delete_dataset(ctx: RunContext[AgentDeps], dataset_id: int) -> dict[str, Any]:
    """删除数据集，会弹出审批，用户批准后才执行。只在用户明确要求删除时调用。

    返回里 contents、comments 是这个数据集原有的内容和评论数，不是删掉的数量；
    recycled_contents、recycled_comments 才是随之从本地内容库删掉的数量（其余内容还在别的
    数据集里，保留）；tasks 是一并删除的采集任务记录数。
    数据集有未结束的采集任务时返回 DATASET_HAS_ACTIVE_TASKS，这时不要调用 stop_collection。

    Args:
        dataset_id: 数据集 ID。
    """
    async with ctx.deps.sessionmaker() as session:
        dataset = await session.get(Dataset, dataset_id)
        impact = await cleanup.impact_of_delete(session, dataset_id)
        if dataset is None or impact is None:
            return error("DATASET_NOT_FOUND", "数据集不存在")
        if impact.active_task_ids:
            return _active(impact.active_task_ids)
        if not ctx.tool_call_approved:
            raise ApprovalRequired(
                metadata={
                    "dataset_id": dataset_id,
                    "name": dataset.name,
                    "impact": impact.model_dump(),
                }
            )
        try:
            result = await cleanup.delete_dataset(session, dataset_id)
        except cleanup.HasActiveTasks as exc:
            return _active(exc.task_ids)
        assert result is not None
        await session.commit()
    ctx.deps.events.publish("dataset.deleted", {"dataset_id": dataset_id})
    await cleanup.vacuum(_db(ctx))
    return result.model_dump()
