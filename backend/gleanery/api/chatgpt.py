"""ChatGPT 套餐的登录路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.deps import get_deps, get_events, get_session
from gleanery.api.errors import ApiError, ErrorBody
from gleanery.api.models import save
from gleanery.api.schemas import ModelConfigOut
from gleanery.deps import AppDeps
from gleanery.events import EventBus
from gleanery.llm.chatgpt import ChatGPTPlan
from gleanery.store.models import ModelConfig

router = APIRouter(prefix="/api/chatgpt", tags=["chatgpt"])
auth_router = APIRouter(include_in_schema=False)
Session = Annotated[AsyncSession, Depends(get_session)]
Deps = Annotated[AppDeps, Depends(get_deps)]
Events = Annotated[EventBus, Depends(get_events)]


def plan(deps: AppDeps) -> ChatGPTPlan:
    if deps.chatgpt is None:
        raise ApiError(503, "CHATGPT_UNAVAILABLE", "ChatGPT 套餐不可用")
    return deps.chatgpt


@router.get("/connect", response_class=RedirectResponse, status_code=303)
async def connect(session: Session, deps: Deps) -> RedirectResponse:
    """跳到授权页。前端用新标签链接打开，授权地址不经过前端 JS。"""
    return RedirectResponse(await plan(deps).start(session), status_code=303)


@router.post("/disconnect", response_model=ModelConfigOut, responses={404: {"model": ErrorBody}})
async def disconnect(session: Session, deps: Deps, events: Events) -> ModelConfigOut:
    """撤销 refresh token 并删除凭证，保留 `client_id` 和 host id。"""
    chatgpt = plan(deps)
    config = await session.scalar(select(ModelConfig).where(ModelConfig.kind == "chatgpt_plan"))
    if config is None:
        raise ApiError(404, "MODEL_CONFIG_NOT_FOUND", "模型配置不存在")
    await chatgpt.disconnect(config)
    result = await save(session, events, config, deps)
    events.publish("app_state.changed")
    return result


@auth_router.get("/auth/callback", response_class=HTMLResponse)
async def callback(request: Request, session: Session, deps: Deps, events: Events) -> HTMLResponse:
    """不要 Cookie，只靠一次性 `state` 和 PKCE 防护。"""
    result = await plan(deps).complete(session, dict(request.query_params))
    if result.changed:
        events.publish("model_configs.changed")
        events.publish("app_state.changed")
    page = f'<!doctype html><meta charset="utf-8"><title>Gleanery</title><p>{result.message}</p>'
    return HTMLResponse(page, status_code=result.status)
