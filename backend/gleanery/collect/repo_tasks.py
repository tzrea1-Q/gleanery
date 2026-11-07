from __future__ import annotations

from datetime import tzinfo
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.schemas_collect import TaskOut
from gleanery.collect import platform_state
from gleanery.collect.plan import PlatformSection
from gleanery.collect.settings import load_rate_limits
from gleanery.collect.types import TaskProgress, TaskSnapshot, TaskStatus, WaitReason
from gleanery.events import EventBus
from gleanery.platforms.types import ContentRef, Platform
from gleanery.store.models import CollectionPlan, CollectionTask, Dataset, TaskItem


async def queue_key(session: AsyncSession, platform: Platform, *, first: bool) -> int:
    aggregate = func.min if first else func.max
    value = await session.scalar(
        select(aggregate(CollectionTask.queue_key)).where(CollectionTask.platform == platform)
    )
    return (value or 0) + (-1 if first else 1)


async def enqueue(
    session: AsyncSession,
    plan: CollectionPlan,
    dataset: Dataset,
    sections: list[PlatformSection],
    resolved: dict[Platform, list[ContentRef]],
    now: int,
) -> list[int]:
    ids = []
    for section in sections:
        targets = list(
            {ref.platform_id: ref for ref in resolved.get(section.platform, [])}.values()
        )
        snapshot = TaskSnapshot(
            plan_title=plan.body.get("title", ""),
            dataset_id=dataset.id,
            dataset_name=dataset.name,
            section=section.model_dump(mode="json"),
            follow_up=plan.body.get("follow_up"),
            confirmed_at=now,
            rate_limits=await load_rate_limits(session, section.platform),
        )
        task = CollectionTask(
            plan_id=plan.id,
            dataset_id=dataset.id,
            conversation_id=plan.conversation_id,
            platform=section.platform,
            status="queued",
            queue_key=await queue_key(session, section.platform, first=False),
            snapshot=snapshot.model_dump(mode="json"),
            progress=TaskProgress(
                discovered=len(targets), planned=section.quantity + len(targets)
            ).model_dump(),
            created_at=now,
            updated_at=now,
        )
        session.add(task)
        await session.flush()
        ids.append(task.id)
        for seq, ref in enumerate(targets, start=1):
            session.add(
                TaskItem(
                    task_id=task.id,
                    platform_id=ref.platform_id,
                    ref=ref.model_dump(mode="json"),
                    source="target",
                    seq=seq,
                    state="pending",
                )
            )
    await session.flush()
    return ids


async def views(
    session: AsyncSession,
    now: int,
    tz: tzinfo | None,
    events: EventBus,
    *,
    task_ids: list[int] | None = None,
    plan_id: int | None = None,
    conversation_id: int | None = None,
) -> list[TaskOut]:
    query = select(CollectionTask).order_by(CollectionTask.created_at, CollectionTask.id)
    if task_ids is not None:
        query = query.where(CollectionTask.id.in_(task_ids))
    if plan_id is not None:
        query = query.where(CollectionTask.plan_id == plan_id)
    if conversation_id is not None:
        query = query.where(CollectionTask.conversation_id == conversation_id)
    tasks = list(await session.scalars(query))
    result = []
    for task in tasks:
        platform = cast(Platform, task.platform)
        wait: WaitReason | None = None
        until = position = None
        if task.status == "queued":
            # 读视图不发事件，见 platform_state.view 的说明。
            platform_view = await platform_state.view(session, platform, now, tz, None)
            position = int(
                await session.scalar(
                    select(func.count())
                    .select_from(CollectionTask)
                    .where(
                        CollectionTask.platform == platform,
                        CollectionTask.status == "queued",
                        (CollectionTask.queue_key < task.queue_key)
                        | (
                            (CollectionTask.queue_key == task.queue_key)
                            & (CollectionTask.id <= task.id)
                        ),
                    )
                )
                or 0
            )
            wait = platform_view["wait_reason"] or "queue"
            until = platform_view["wait_until"]
        progress = TaskProgress.model_validate(task.progress)
        progress.parse_stats.pop("__items", None)
        result.append(
            TaskOut(
                id=task.id,
                plan_id=task.plan_id,
                dataset_id=task.dataset_id,
                platform=platform,
                status=cast(TaskStatus, task.status),
                reason=task.reason,
                wait_reason=wait,
                wait_until=until,
                queue_position=position,
                snapshot=task.snapshot,
                progress=progress,
                created_at=task.created_at,
                started_at=task.started_at,
                finished_at=task.finished_at,
            )
        )
    return result
