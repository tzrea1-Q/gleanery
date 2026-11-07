from typing import Any

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.store.models import Setting


async def get_setting(session: AsyncSession, key: str, default: Any = None) -> Any:
    row = await session.get(Setting, key)
    return row.value if row else default


async def set_setting(session: AsyncSession, key: str, value: Any) -> None:
    # 两个会话同时首次写同一个键时，先查后插会撞主键（e2e 里出现过），所以用 upsert。
    await session.execute(
        insert(Setting)
        .values(key=key, value=value)
        .on_conflict_do_update(index_elements=[Setting.key], set_={"value": value})
    )
    row = session.identity_map.get(session.sync_session.identity_key(Setting, key))
    if row is not None:
        await session.refresh(row)
