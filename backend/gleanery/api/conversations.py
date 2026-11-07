"""对话列表与历史。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.agent.follow_up import approval_pending
from gleanery.agent.injection_reports import OPEN_REPORT_KEY
from gleanery.api.deps import get_deps, get_events, get_session
from gleanery.api.errors import ApiError, ErrorBody
from gleanery.api.schemas import ConversationDetail, ConversationSummary
from gleanery.api.schemas_reports import WorkspaceState
from gleanery.deps import AppDeps
from gleanery.events import EventBus
from gleanery.store import repo_conversations as repo
from gleanery.store.models import CollectionPlan, Conversation
from gleanery.store.repo_settings import set_setting

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def summary(conversation: Conversation) -> ConversationSummary:
    return ConversationSummary(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


async def find(session: AsyncSession, conversation_id: int) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise ApiError(404, "CONVERSATION_NOT_FOUND", "对话不存在")
    return conversation


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ConversationSummary]:
    """按 updated_at 倒序。"""
    return [summary(item) for item in await repo.list_all(session)]


@router.post("", response_model=ConversationSummary, status_code=201)
async def create_conversation(
    session: Annotated[AsyncSession, Depends(get_session)],
    deps: Annotated[AppDeps, Depends(get_deps)],
    events: Annotated[EventBus, Depends(get_events)],
) -> ConversationSummary:
    conversation = await repo.create(session, deps.clock.now_ms())
    events.publish("conversation.updated", {"conversation_id": conversation.id})
    return summary(conversation)


@router.get(
    "/{conversation_id}", response_model=ConversationDetail, responses={404: {"model": ErrorBody}}
)
async def get_conversation(
    conversation_id: int, request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> ConversationDetail:
    conversation = await find(session, conversation_id)
    rows = await repo.rows(session, conversation_id)
    # 整段一起转换：工具调用和工具结果分在两条消息里，逐条转换会配不上对，
    # 刷新后卡片停在"等待审批"而不显示（M2 自查发现，M1 起就有）。
    history = ModelMessagesTypeAdapter.validate_python([row.payload for row in rows])
    # 每条模型回复对应一条 assistant UI 消息，按顺序配上生成它的模型。
    models = iter([row.model_name for row in rows if row.kind == "response"])
    messages = []
    for ui in VercelAIAdapter.dump_messages(history, sdk_version=7):
        data = ui.model_dump(mode="json", by_alias=True, exclude_none=True)
        if ui.role == "assistant":
            data["metadata"] = {"model": next(models, None)}
        messages.append(data)
    return ConversationDetail(
        **summary(conversation).model_dump(),
        messages=messages,
        running=request.app.state.runs.busy(conversation_id),
    )


@router.delete("/{conversation_id}", status_code=204, responses={404: {"model": ErrorBody}})
async def delete_conversation(
    conversation_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    events: Annotated[EventBus, Depends(get_events)],
) -> None:
    await repo.delete(session, await find(session, conversation_id))
    events.publish("conversation.deleted", {"conversation_id": conversation_id})


@router.put(
    "/{conversation_id}/workspace",
    response_model=WorkspaceState,
    responses={404: {"model": ErrorBody}},
)
async def put_workspace(
    conversation_id: int,
    body: WorkspaceState,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkspaceState:
    """前端在报告标签显示的报告变化时调用，下一轮注入"工作区当前打开的报告"。"""
    await find(session, conversation_id)
    await set_setting(
        session, OPEN_REPORT_KEY.format(conversation_id=conversation_id), body.report_id
    )
    await session.commit()
    return body


class FollowUpRequest(BaseModel):
    plan_id: int


@router.post(
    "/{conversation_id}/follow-up",
    status_code=202,
    responses={404: {"model": ErrorBody}, 409: {"model": ErrorBody}},
)
async def follow_up(
    conversation_id: int,
    body: FollowUpRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    await find(session, conversation_id)
    plan = await session.get(CollectionPlan, body.plan_id)
    if plan is None or plan.conversation_id != conversation_id:
        raise ApiError(404, "PLAN_NOT_FOUND", "计划不存在")
    runs = request.app.state.runs
    follow_ups = request.app.state.follow_ups
    if runs.busy(conversation_id) or conversation_id in follow_ups.pending:
        raise ApiError(409, "CONVERSATION_BUSY", "Agent 正在运行，请稍候")
    follow_ups.pending.add(conversation_id)
    try:
        if approval_pending(await repo.history(session, conversation_id)):
            raise ApiError(409, "APPROVAL_PENDING", "请先处理待审批的操作")
        if await request.app.state.deps.model_resolver(session) is None:
            raise ApiError(409, "NO_MODEL", "没有可用的当前模型", "请先选择模型")
        follow_ups.spawn(follow_ups.retry(conversation_id, body.plan_id))
    except BaseException:
        follow_ups.pending.discard(conversation_id)
        raise
