"""应用状态：当前模型、使用声明。"""

from typing import Annotated, cast

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.deps import get_deps, get_events, get_session
from gleanery.api.errors import ApiError, ErrorBody
from gleanery.api.schemas import AppState, ConfigKind, CurrentModel, CurrentModelSet
from gleanery.deps import AppDeps
from gleanery.events import EventBus
from gleanery.store.models import ModelConfig
from gleanery.store.repo_settings import get_setting, set_setting

router = APIRouter(prefix="/api/app-state", tags=["app-state"])


async def state(session: AsyncSession, deps: AppDeps) -> AppState:
    current = await get_setting(session, "current_model")
    config = await session.get(ModelConfig, current["config_id"]) if current else None
    return AppState(
        current_model=_current_model(config, current["model"]) if config and current else None,
        disclaimer_acknowledged=await get_setting(session, "disclaimer_acknowledged", False),
        chatgpt_notice_acknowledged=await get_setting(
            session, "chatgpt_notice_acknowledged", False
        ),
        credential_backend=deps.credential_store.backend,
    )


def _current_model(config: ModelConfig, model: str) -> CurrentModel:
    favorite = next((f for f in config.favorites if f["name"] == model), None)
    reason = None
    if config.status != "ok":
        reason = config.status_reason or "模型配置不可用"
    elif favorite is None or favorite["tool_test"] == "untested":
        reason = "需要重新测试工具调用"
    elif favorite["tool_test"] != "ok":
        reason = "未通过工具调用测试"
    status = (
        "ok"
        if not reason
        else "needs_reconnect"
        if config.status == "needs_reconnect"
        else "unavailable"
    )
    return CurrentModel(
        config_id=config.id,
        config_name=config.name,
        kind=cast(ConfigKind, config.kind),
        model=model,
        status=status,
        status_reason=reason,
    )


@router.get("", response_model=AppState)
async def get_app_state(
    session: Annotated[AsyncSession, Depends(get_session)],
    deps: Annotated[AppDeps, Depends(get_deps)],
) -> AppState:
    return await state(session, deps)


@router.put(
    "/current-model",
    response_model=AppState,
    responses={
        409: {"model": ErrorBody, "description": "MODEL_NOT_USABLE：该模型未通过工具调用测试"}
    },
)
async def set_current_model(
    body: CurrentModelSet,
    session: Annotated[AsyncSession, Depends(get_session)],
    deps: Annotated[AppDeps, Depends(get_deps)],
    events: Annotated[EventBus, Depends(get_events)],
) -> AppState:
    config = await session.get(ModelConfig, body.config_id)
    if (
        not config
        or config.status != "ok"
        or not any(f["name"] == body.model and f["tool_test"] == "ok" for f in config.favorites)
    ):
        raise ApiError(409, "MODEL_NOT_USABLE", "该模型不可用或未通过工具调用测试")
    await set_setting(session, "current_model", body.model_dump())
    await session.commit()
    events.publish("app_state.changed")
    return await state(session, deps)


@router.post("/disclaimer-ack", response_model=AppState)
async def acknowledge_disclaimer(
    session: Annotated[AsyncSession, Depends(get_session)],
    deps: Annotated[AppDeps, Depends(get_deps)],
    events: Annotated[EventBus, Depends(get_events)],
) -> AppState:
    await set_setting(session, "disclaimer_acknowledged", True)
    await session.commit()
    events.publish("app_state.changed")
    return await state(session, deps)


@router.post("/chatgpt-notice-ack", response_model=AppState)
async def acknowledge_chatgpt_notice(
    session: Annotated[AsyncSession, Depends(get_session)],
    deps: Annotated[AppDeps, Depends(get_deps)],
    events: Annotated[EventBus, Depends(get_events)],
) -> AppState:
    await set_setting(session, "chatgpt_notice_acknowledged", True)
    await session.commit()
    events.publish("app_state.changed")
    return await state(session, deps)
