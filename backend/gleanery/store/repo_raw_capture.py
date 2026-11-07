from __future__ import annotations

import gzip

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gleanery.platforms.types import Capture
from gleanery.store.models import RawCapture


async def save(session: AsyncSession, task_id: int, capture: Capture) -> RawCapture:
    row = RawCapture(
        task_id=task_id,
        platform=capture.platform,
        kind=capture.kind,
        url_path=capture.url_path,
        captured_at=capture.captured_at,
        body_gz=gzip.compress(capture.model_dump_json().encode()),
    )
    session.add(row)
    await session.flush()
    return row


async def list_for_task(session: AsyncSession, task_id: int) -> list[RawCapture]:
    result = await session.scalars(
        select(RawCapture).where(RawCapture.task_id == task_id).order_by(RawCapture.id)
    )
    return list(result)


async def get(session: AsyncSession, capture_id: int) -> RawCapture | None:
    return await session.get(RawCapture, capture_id)


def decompress(row: RawCapture) -> Capture:
    return Capture.model_validate_json(gzip.decompress(row.body_gz))


class RawCaptureSink:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], task_id: int):
        self.session_factory = session_factory
        self.task_id = task_id

    async def save(self, capture: Capture) -> None:
        async with self.session_factory.begin() as session:
            await save(session, self.task_id, capture)
