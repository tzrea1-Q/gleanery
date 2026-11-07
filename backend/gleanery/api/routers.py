"""`ROUTERS` 由 `create_app` 统一挂载。单独成模块，免得导入 `gleanery.api` 下的 schema 时连带加载全部路由。"""

from fastapi import APIRouter

from gleanery.api import (
    app_state,
    chat,
    chatgpt,
    collect_settings,
    contents,
    conversations,
    data,
    data_settings,
    datasets,
    events,
    exports,
    models,
    plans,
    platforms,
    reports,
    tasks,
)

ROUTERS: list[APIRouter] = [
    conversations.router,
    chat.router,
    events.router,
    models.router,
    app_state.router,
    plans.router,
    tasks.router,
    platforms.router,
    datasets.router,
    collect_settings.router,
    contents.router,
    exports.router,
    data.router,
    data_settings.router,
    reports.router,
    chatgpt.router,
    chatgpt.auth_router,
]
