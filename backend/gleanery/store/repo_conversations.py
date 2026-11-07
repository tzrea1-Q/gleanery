from collections.abc import Sequence

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.ui._utils import get_ui_message_id
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.store.models import Conversation, Message


async def create(session: AsyncSession, now: int) -> Conversation:
    conversation = Conversation(title="", created_at=now, updated_at=now)
    session.add(conversation)
    await session.commit()
    return conversation


async def list_all(session: AsyncSession) -> list[Conversation]:
    result = await session.scalars(
        select(Conversation).order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    )
    return list(result)


async def rows(session: AsyncSession, conversation_id: int) -> list[Message]:
    result = await session.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
    )
    return list(result)


async def history(session: AsyncSession, conversation_id: int) -> list[ModelMessage]:
    return ModelMessagesTypeAdapter.validate_python(
        [row.payload for row in await rows(session, conversation_id)]
    )


async def truncate_after(session: AsyncSession, conversation_id: int, ui_message_id: str) -> bool:
    """删掉 UI 消息 `ui_message_id` 之后的所有消息，用于重试和重新生成。找不到时返回 False。"""
    stored = await rows(session, conversation_id)
    messages = ModelMessagesTypeAdapter.validate_python([row.payload for row in stored])
    for row, message in zip(stored, messages, strict=True):
        if get_ui_message_id(message) == ui_message_id:
            await session.execute(
                sql_delete(Message).where(
                    Message.conversation_id == conversation_id, Message.seq > row.seq
                )
            )
            await session.commit()
            return True
    return False


async def append(
    session: AsyncSession,
    conversation: Conversation,
    messages: Sequence[ModelMessage],
    model_name: str | None,
    now: int,
) -> None:
    seq = await session.scalar(
        select(func.max(Message.seq)).where(Message.conversation_id == conversation.id)
    )
    payloads = ModelMessagesTypeAdapter.dump_python(list(messages), mode="json")
    for offset, (message, payload) in enumerate(
        zip(messages, payloads, strict=True), start=(seq if seq is not None else -1) + 1
    ):
        is_response = isinstance(message, ModelResponse)
        session.add(
            Message(
                conversation_id=conversation.id,
                seq=offset,
                kind="response" if is_response else "request",
                payload=payload,
                model_name=model_name if is_response else None,
                created_at=now,
            )
        )
    conversation.updated_at = now
    await session.commit()


async def rename(session: AsyncSession, conversation: Conversation, title: str) -> None:
    conversation.title = title


async def delete(session: AsyncSession, conversation: Conversation) -> None:
    await session.delete(conversation)
    await session.commit()
