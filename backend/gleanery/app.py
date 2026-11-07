import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from gleanery import __version__, store
from gleanery.agent.follow_up import FollowUps
from gleanery.agent.runs import ConversationRuns
from gleanery.api.errors import ApiError
from gleanery.api.routers import ROUTERS
from gleanery.collect.login import LoginCoordinator
from gleanery.collect.service import CollectService
from gleanery.deps import AppDeps
from gleanery.events import EventBus
from gleanery.query.sql import ReadOnlySql
from gleanery.security import LocalSecurity
from gleanery.store.db import DB_FILENAME
from gleanery.store.retention import RetentionJob


class SPAFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope):
        if path == "api" or path.startswith("api/") or path == "auth" or path.startswith("auth/"):
            raise HTTPException(status_code=404)
        try:
            response = await super().get_response(path, scope)
            if response.status_code != 404 and path not in (".", "index.html"):
                return response
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        response = await super().get_response("index.html", scope)
        # 页面每次回源校验，重新构建后才能拿到新的资源文件名；assets 文件名带哈希，照常缓存
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(deps: AppDeps) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.db = await store.open_database(deps.data_dir)
        app.state.collect = CollectService(
            app.state.db.sessionmaker,
            app.state.events,
            deps.clock,
            deps.platform_runtime,
            tz=deps.tz,
            app_version=__version__,
        )
        app.state.runs = ConversationRuns(app.state.events)
        app.state.follow_ups = FollowUps(app)
        app.state.follow_ups.start()
        await app.state.collect.start()
        app.state.login = LoginCoordinator(
            deps.platform_runtime, app.state.collect, app.state.db.sessionmaker, app.state.events
        )
        app.state.sql = ReadOnlySql(deps.data_dir / DB_FILENAME)
        app.state.retention = RetentionJob(app.state.db, deps.clock)
        await app.state.retention.start()
        try:
            yield
        finally:
            await app.state.retention.stop()
            await app.state.login.close()
            await app.state.runs.close()
            await app.state.follow_ups.close()
            await app.state.collect.stop()
            if deps.chatgpt is not None:
                await deps.chatgpt.close()
            if deps.platform_runtime is not None:
                await deps.platform_runtime.close()
            app.state.events.close()
            await app.state.db.close()

    app = FastAPI(title="Gleanery", version=__version__, lifespan=lifespan)
    app.state.deps = deps
    app.state.events = EventBus()
    app.add_middleware(LocalSecurity, deps=deps)

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(exc.body.model_dump(), status_code=exc.status)

    @app.get("/auth/launch", include_in_schema=False, response_model=None)
    async def launch(token: str = "", next: str = "/") -> HTMLResponse | RedirectResponse:
        if not secrets.compare_digest(token.encode(), deps.launch_token.encode()):
            return HTMLResponse("启动令牌无效，请运行 gleanery 命令重新打开。", status_code=403)
        if not next.startswith("/") or next.startswith("//") or "\\" in next:
            next = "/"
        response = RedirectResponse(next, status_code=303)
        response.set_cookie("gleanery_session", deps.launch_token, httponly=True, samesite="strict")
        return response

    for router in ROUTERS:
        app.include_router(router)
    if deps.static_dir is not None:
        app.mount("/", SPAFiles(directory=deps.static_dir, html=True), name="static")
    return app
