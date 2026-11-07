"""模型配置。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.deps import get_deps, get_events, get_session
from gleanery.api.errors import ApiError, ErrorBody
from gleanery.api.schemas import (
    FavoriteAdd,
    ModelConfigCreate,
    ModelConfigOut,
    ModelConfigUpdate,
    ModelPreset,
)
from gleanery.deps import AppDeps
from gleanery.events import EventBus
from gleanery.llm.presets import PRESETS
from gleanery.llm.probe import probe_tool_call, refresh
from gleanery.store.models import ModelConfig
from gleanery.store.repo_model_configs import list_configs as read_configs
from gleanery.store.repo_settings import get_setting, set_setting

router = APIRouter(prefix="/api", tags=["models"])
_404: dict[int | str, dict[str, Any]] = {404: {"model": ErrorBody}}
Session = Annotated[AsyncSession, Depends(get_session)]
Deps = Annotated[AppDeps, Depends(get_deps)]
Events = Annotated[EventBus, Depends(get_events)]


def output(config: ModelConfig, deps: AppDeps) -> ModelConfigOut:
    return ModelConfigOut.model_validate(
        {
            **{
                name: getattr(config, name)
                for name in ModelConfigOut.model_fields
                if name != "has_credential"
            },
            "has_credential": (
                bool(deps.chatgpt and deps.chatgpt.has_refresh_token(config.id))
                if config.kind == "chatgpt_plan"
                else bool(deps.credential_store.get(config.id))
            ),
        }
    )


async def find(session: AsyncSession, config_id: int) -> ModelConfig:
    config = await session.get(ModelConfig, config_id)
    if not config:
        raise ApiError(404, "MODEL_CONFIG_NOT_FOUND", "模型配置不存在")
    return config


async def save(
    session: AsyncSession, events: EventBus, config: ModelConfig, deps: AppDeps
) -> ModelConfigOut:
    config.updated_at = deps.clock.now_ms()
    await session.commit()
    events.publish("model_configs.changed")
    events.publish("app_state.changed")
    return output(config, deps)


async def clear_current(
    session: AsyncSession, config_id: int, model: str | None, events: EventBus
) -> None:
    current = await get_setting(session, "current_model")
    if (
        current
        and current["config_id"] == config_id
        and (model is None or current["model"] == model)
    ):
        await set_setting(session, "current_model", None)
        events.publish("app_state.changed")


@router.get("/model-presets", response_model=list[ModelPreset])
async def list_presets() -> list[ModelPreset]:
    return PRESETS


@router.get("/model-configs", response_model=list[ModelConfigOut])
async def list_configs(session: Session, deps: Deps) -> list[ModelConfigOut]:
    return [output(c, deps) for c in await read_configs(session)]


@router.post("/model-configs", response_model=ModelConfigOut, status_code=201)
async def create_config(
    body: ModelConfigCreate, session: Session, deps: Deps, events: Events
) -> ModelConfigOut:
    """保存凭证、测连通、拉模型列表。连不通也保存，`status` 标为 unavailable。"""
    preset = next((p for p in PRESETS if p.id == body.preset), None)
    if not preset:
        raise ApiError(400, "INVALID_PRESET", "未知预设")
    now = deps.clock.now_ms()
    config = ModelConfig(
        kind=preset.kind,
        name=body.name,
        preset=preset.id,
        base_url=body.base_url,
        api_style=preset.api_style,
        status="unavailable",
        status_reason=None,
        available_models=None,
        model_labels=None,
        client_id=None,
        models_fetched_at=None,
        favorites=[],
        created_at=now,
        updated_at=now,
    )
    session.add(config)
    await session.flush()
    if body.api_key:
        deps.credential_store.set(config.id, body.api_key)
    await refresh(config, body.api_key, deps.llm_transport, now)
    return await save(session, events, config, deps)


@router.patch("/model-configs/{config_id}", response_model=ModelConfigOut, responses=_404)
async def update_config(
    config_id: int, body: ModelConfigUpdate, session: Session, deps: Deps, events: Events
) -> ModelConfigOut:
    config = await find(session, config_id)
    if config.kind == "chatgpt_plan":
        if body.base_url is not None or body.api_key is not None:
            raise ApiError(400, "INVALID_REQUEST", "ChatGPT 套餐只能修改名称")
        if body.name is not None:
            config.name = body.name
        return await save(session, events, config, deps)
    if body.name is not None:
        config.name = body.name
    # 前端编辑时总会带上 base_url，只有值真的变了才算"换了服务地址"。
    base_url_changed = body.base_url is not None and body.base_url != config.base_url
    if body.base_url is not None and base_url_changed:
        config.base_url = body.base_url
    if body.api_key is not None:
        if body.api_key:
            deps.credential_store.set(config_id, body.api_key)
        else:
            deps.credential_store.delete(config_id)
    if base_url_changed or body.api_key is not None:
        await refresh(
            config, deps.credential_store.get(config_id), deps.llm_transport, deps.clock.now_ms()
        )
    if base_url_changed:
        # 换了服务地址，同名模型未必是同一个，工具调用要重测；只换 Key 不影响模型能力。
        config.favorites = [
            {**f, "tool_test": "untested", "tool_test_error": None, "tested_at": None}
            for f in config.favorites
        ]
    return await save(session, events, config, deps)


@router.delete("/model-configs/{config_id}", status_code=204, responses=_404)
async def delete_config(config_id: int, session: Session, deps: Deps, events: Events) -> None:
    """删除凭证；当前模型属于它时清空当前模型。"""
    config = await find(session, config_id)
    if config.kind == "chatgpt_plan":
        if deps.chatgpt is None:
            raise ApiError(503, "CHATGPT_UNAVAILABLE", "ChatGPT 套餐不可用")
        await deps.chatgpt.forget(config)
    else:
        deps.credential_store.delete(config_id)
    await clear_current(session, config_id, None, events)
    await session.delete(config)
    await session.commit()
    events.publish("model_configs.changed")


@router.post(
    "/model-configs/{config_id}/refresh-models", response_model=ModelConfigOut, responses=_404
)
async def refresh_models(
    config_id: int, session: Session, deps: Deps, events: Events
) -> ModelConfigOut:
    config = await find(session, config_id)
    await refresh(
        config,
        deps.credential_store.get(config_id),
        deps.llm_transport,
        deps.clock.now_ms(),
        deps.chatgpt,
    )
    return await save(session, events, config, deps)


async def run_test(config: ModelConfig, model: str, deps: AppDeps) -> None:
    if config.status == "needs_reconnect":
        raise ApiError(409, "MODEL_RECONNECT_REQUIRED", "ChatGPT 套餐需要重新连接")
    error = await probe_tool_call(
        config, model, deps.credential_store.get(config.id), deps.llm_transport, deps.chatgpt
    )
    favorite = {
        "name": model,
        "tool_test": "failed" if error else "ok",
        "tool_test_error": error,
        "tested_at": deps.clock.now_ms(),
    }
    config.favorites = [f for f in config.favorites if f["name"] != model] + [favorite]


@router.post("/model-configs/{config_id}/favorites", response_model=ModelConfigOut, responses=_404)
async def add_favorite(
    config_id: int, body: FavoriteAdd, session: Session, deps: Deps, events: Events
) -> ModelConfigOut:
    """勾选常用模型，并立即带假工具发流式请求测工具调用。"""
    config = await find(session, config_id)
    await run_test(config, body.model, deps)
    return await save(session, events, config, deps)


@router.delete(
    "/model-configs/{config_id}/favorites/{model:path}",
    response_model=ModelConfigOut,
    responses=_404,
)
async def remove_favorite(
    config_id: int, model: str, session: Session, deps: Deps, events: Events
) -> ModelConfigOut:
    """取消勾选；它是当前模型时清空当前模型。"""
    config = await find(session, config_id)
    if not any(f["name"] == model for f in config.favorites):
        raise ApiError(404, "MODEL_NOT_FOUND", "常用模型不存在")
    config.favorites = [f for f in config.favorites if f["name"] != model]
    await clear_current(session, config_id, model, events)
    return await save(session, events, config, deps)


@router.post(
    "/model-configs/{config_id}/favorites/{model:path}/test",
    response_model=ModelConfigOut,
    responses=_404,
)
async def retest_favorite(
    config_id: int, model: str, session: Session, deps: Deps, events: Events
) -> ModelConfigOut:
    config = await find(session, config_id)
    if not any(f["name"] == model for f in config.favorites):
        raise ApiError(404, "MODEL_NOT_FOUND", "常用模型不存在")
    await run_test(config, model, deps)
    return await save(session, events, config, deps)
