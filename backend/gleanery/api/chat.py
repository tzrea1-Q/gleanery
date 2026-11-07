"""AI SDK v7 对话流。"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import ValidationError
from pydantic_ai import DeferredToolRequests
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.ui._event_stream import NativeEvent
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai.response_types import BaseChunk, ErrorChunk
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.agent import build_agent
from gleanery.agent.deps import AgentDeps, agent_deps
from gleanery.agent.injection import instructions
from gleanery.api.conversations import find
from gleanery.api.deps import get_deps, get_events, get_session
from gleanery.api.errors import ApiError, ErrorBody
from gleanery.deps import AppDeps, ResolvedModel
from gleanery.events import EventBus
from gleanery.llm.errors import ModelFailure, classify_model_error
from gleanery.store import repo_conversations as repo
from gleanery.store.models import Conversation
from gleanery.store.repo_model_configs import mark_config_status

router = APIRouter(prefix="/api", tags=["chat"])


async def _on_model_failure(
    session: AsyncSession, resolved: ResolvedModel, events: EventBus, failure: ModelFailure
) -> None:
    if resolved.config_id is not None and failure.config_status is not None:
        await mark_config_status(
            session, resolved.config_id, failure.config_status, failure.config_reason
        )
        events.publish("model_configs.changed")
        events.publish("app_state.changed")


logger = logging.getLogger(__name__)


@router.post(
    "/chat",
    response_class=Response,
    responses={
        200: {"content": {"text/event-stream": {}}},
        404: {"model": ErrorBody},
        409: {"model": ErrorBody, "description": "NO_MODEL：没有可用的当前模型"},
    },
)
async def chat(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    deps: Annotated[AppDeps, Depends(get_deps)],
    events: Annotated[EventBus, Depends(get_events)],
) -> Response:
    try:
        adapter = await VercelAIAdapter[AgentDeps, str | DeferredToolRequests].from_request(
            request, agent=build_agent(), sdk_version=7, manage_message_history="server"
        )
    except ValidationError as exc:
        raise ApiError(422, "INVALID_REQUEST", "对话请求格式无效") from exc
    try:
        conversation_id = int(adapter.run_input.id)
    except ValueError as exc:
        raise ApiError(404, "CONVERSATION_NOT_FOUND", "对话不存在") from exc
    conversation = await find(session, conversation_id)
    runs = request.app.state.runs
    if (
        runs.busy(conversation_id) == "follow_up"
        or conversation_id in request.app.state.follow_ups.pending
    ):
        raise ApiError(409, "CONVERSATION_BUSY", "Agent 正在整理采集结果，请稍候")
    if conversation_id in runs.detached:
        raise ApiError(409, "CONVERSATION_BUSY", "Agent 正在回复上一条消息，请稍候")
    resolved = await deps.model_resolver(session)
    if resolved is None:
        raise ApiError(409, "NO_MODEL", "没有可用的当前模型", "请先选择模型")
    approvals = adapter.deferred_tool_results
    is_approval = approvals is not None
    if is_approval:
        if not adapter.run_input.messages or adapter.run_input.messages[-1].role != "assistant":
            raise ApiError(422, "INVALID_REQUEST", "审批请求格式无效")
        history = await repo.history(session, conversation_id)
    else:
        if len(adapter.run_input.messages) != 1 or adapter.run_input.messages[0].role != "user":
            raise ApiError(422, "INVALID_REQUEST", "请提供一条用户消息")
        incoming = adapter.sanitize_messages(adapter.messages)
        incoming_id = adapter.run_input.messages[0].id
        already_saved = await repo.truncate_after(session, conversation_id, incoming_id)
        history = await repo.history(session, conversation_id)
        if not already_saved:
            if not conversation.title:
                text = " ".join(
                    part.content
                    for message in incoming
                    if isinstance(message, ModelRequest)
                    for part in message.parts
                    if isinstance(part, UserPromptPart) and isinstance(part.content, str)
                )
                await repo.rename(
                    session, conversation, text.strip().replace("\n", " ").replace("\r", " ")[:30]
                )
            await repo.append(session, conversation, incoming, None, deps.clock.now_ms())
            events.publish("conversation.updated", {"conversation_id": conversation_id})

    # 系统注入：任务状态变化与报告，作为本轮的附加指令，不进消息历史。
    injected = await instructions(session, conversation_id)
    await session.commit()

    error: Exception | None = None

    async def native() -> AsyncIterator[NativeEvent]:
        nonlocal error
        try:
            async for event in adapter.run_stream_native(
                message_history=history,
                model=resolved.model,
                instructions=injected,
                deps=agent_deps(request.app, conversation_id),
            ):
                yield event
        except Exception as exc:
            error = exc
            # 工具参数反复校验失败时，校验错误在 __cause__ 里；记下来才能据此改工具描述。
            # 只记模型行为类错误：它们只含模型生成的参数，不含请求头与 Key。
            if isinstance(exc, UnexpectedModelBehavior):
                logger.warning("模型行为异常：%s；原因：%s", exc, exc.__cause__)
            raise

    async def run_chunks(db: AsyncSession) -> AsyncIterator[BaseChunk]:
        async def complete(result: AgentRunResult[str | DeferredToolRequests]) -> None:
            messages = [
                message
                for message in result.new_messages()
                if message.kind == "response"
                or not any(isinstance(part, UserPromptPart) for part in message.parts)
            ]
            saved = await db.get(Conversation, conversation_id)
            if messages and saved:
                await repo.append(db, saved, messages, resolved.model_name, deps.clock.now_ms())
                events.publish("conversation.updated", {"conversation_id": conversation_id})

        async for chunk in adapter.transform_stream(native(), on_complete=complete):
            if isinstance(chunk, ErrorChunk):
                failure = classify_model_error(error, resolved.kind)
                await _on_model_failure(db, resolved, events, failure)
                yield ErrorChunk(error_text=failure.body.model_dump_json())
            else:
                yield chunk

    queue: asyncio.Queue[BaseChunk | None] = asyncio.Queue()

    # 请求级会话在响应结束时关闭，客户端断开后它就不能用了，所以这一轮自己开会话。
    async def produce() -> None:
        try:
            async with (
                runs.hold(conversation_id, "chat"),
                request.app.state.db.sessionmaker() as db,
            ):
                async for chunk in run_chunks(db):
                    queue.put_nowait(chunk)
        finally:
            queue.put_nowait(None)

    task = runs.spawn(conversation_id, produce())

    async def chunks() -> AsyncIterator[BaseChunk]:
        try:
            while (chunk := await queue.get()) is not None:
                yield chunk
        finally:
            runs.detach(conversation_id, task)

    return adapter.streaming_response(chunks())
