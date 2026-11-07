from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.collect.plan import PlanBody
from gleanery.store.models import CollectionPlan


class PlanLocked(Exception):
    pass


class VersionConflict(Exception):
    def __init__(self, current: CollectionPlan) -> None:
        self.current = current
        super().__init__(str(current.version))


async def create_draft(
    session: AsyncSession, conversation_id: int | None, body: PlanBody, now: int
) -> CollectionPlan:
    plan = CollectionPlan(
        conversation_id=conversation_id,
        status="draft",
        version=1,
        body=body.model_dump(mode="json"),
        target_dataset_id=body.target_dataset_id,
        created_at=now,
        updated_at=now,
    )
    session.add(plan)
    await session.flush()
    return plan


async def get(session: AsyncSession, plan_id: int) -> CollectionPlan | None:
    return await session.get(CollectionPlan, plan_id, populate_existing=True)


async def replace(
    session: AsyncSession, plan_id: int, base_version: int, body: PlanBody, now: int
) -> CollectionPlan | None:
    result = await session.execute(
        update(CollectionPlan)
        .where(
            CollectionPlan.id == plan_id,
            CollectionPlan.status == "draft",
            CollectionPlan.version == base_version,
        )
        .values(
            body=body.model_dump(mode="json"),
            target_dataset_id=body.target_dataset_id,
            version=CollectionPlan.version + 1,
            updated_at=now,
        )
        .returning(CollectionPlan.id)
    )
    updated = result.scalar_one_or_none()
    plan = await get(session, plan_id)
    if updated is None and plan is not None:
        if plan.status != "draft":
            raise PlanLocked()
        raise VersionConflict(plan)
    return plan


async def confirm(session: AsyncSession, plan: CollectionPlan, dataset_id: int, now: int) -> None:
    result = await session.execute(
        update(CollectionPlan)
        .where(
            CollectionPlan.id == plan.id,
            CollectionPlan.status == "draft",
            CollectionPlan.version == plan.version,
        )
        .values(status="confirmed", target_dataset_id=dataset_id, confirmed_at=now, updated_at=now)
        .returning(CollectionPlan.id)
    )
    if result.scalar_one_or_none() is None:
        current = await get(session, plan.id)
        if current is not None and current.status == "draft":
            raise VersionConflict(current)
        raise PlanLocked()
    await session.refresh(plan)
