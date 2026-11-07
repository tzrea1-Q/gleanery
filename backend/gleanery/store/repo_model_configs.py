from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.store.models import ModelConfig


async def list_configs(session: AsyncSession) -> list[ModelConfig]:
    return list((await session.scalars(select(ModelConfig).order_by(ModelConfig.id))).all())


async def mark_config_unavailable(session: AsyncSession, config_id: int, reason: str) -> None:
    await mark_config_status(session, config_id, "unavailable", reason)


async def mark_config_status(
    session: AsyncSession, config_id: int, status: str, reason: str | None
) -> None:
    config = await session.get(ModelConfig, config_id)
    if config:
        config.status = status
        config.status_reason = reason
        await session.commit()
