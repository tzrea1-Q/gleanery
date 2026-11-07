import asyncio
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gleanery.api.collect_settings import router as settings_router
from gleanery.api.errors import ApiError
from gleanery.api.platforms import router as platforms_router
from gleanery.collect.login import LoginCoordinator
from gleanery.collect.runtime import PlatformRuntime
from gleanery.collect.service import CollectService, PlatformView
from gleanery.events import EventBus
from gleanery.platforms.errors import ProfileInUse
from gleanery.platforms.types import ProbeResult
from gleanery.store import open_database
from gleanery.store.repo_settings import get_setting


async def test_settings_and_platforms(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    collect = MagicMock()

    async def view(session, platform):
        return PlatformView(
            platform=platform,
            state="normal",
            reason=None,
            wait_reason=None,
            wait_until=None,
            cooldown_until=None,
            locked_until=None,
            quota_used=0,
            daily_quota=100,
            warmup_until=None,
            last_probe_at=None,
            last_probe_ok=None,
            last_probe_detail=None,
            queue_length=0,
        )

    collect.platform_view = view
    collect.on_probe = AsyncMock()
    collect.on_login_lost = AsyncMock()
    runtime = MagicMock()
    runtime.platforms = frozenset({"bili"})
    fetcher = runtime.fetcher.return_value
    fetcher.probe = AsyncMock(return_value=ProbeResult(logged_in=False))
    fetcher.close = AsyncMock()
    runtime.browser_kind.return_value = None
    runtime.browser_running.return_value = False
    login = LoginCoordinator(
        cast(PlatformRuntime, runtime), cast(CollectService, collect), db.sessionmaker, EventBus()
    )
    app = FastAPI()
    app.state.db = db
    app.state.collect = collect
    app.state.login = login
    app.include_router(settings_router)
    app.include_router(platforms_router)

    @app.exception_handler(ApiError)
    async def handle_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body.model_dump())

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            platforms = (await client.get("/api/platforms")).json()
            assert [item["platform"] for item in platforms] == ["bili", "xhs"]
            assert (await client.post("/api/platforms/xhs/probe")).status_code == 409
            assert (await client.post("/api/platforms/bili/probe")).status_code == 200
            collect.on_login_lost.assert_awaited_once_with("bili")
            fetcher.close.assert_awaited_once()
            response = await client.patch(
                "/api/collect-settings", json={"platforms": {"bili": {"page_interval": [4, 8]}}}
            )
            assert response.status_code == 200
            async with db.sessionmaker() as session:
                assert await get_setting(session, "collect.rate_limits.bili") == {
                    "page_interval": [4.0, 8.0]
                }
            response = await client.patch(
                "/api/collect-settings", json={"platforms": {"bili": {"page_interval": [1, 8]}}}
            )
            assert response.status_code == 422 and response.json()["code"] == "RATE_TOO_LOOSE"
            # 评论翻页间隔的下限是它自己默认下界的一半（2 → 1），不是页面间隔的下限。
            response = await client.patch(
                "/api/collect-settings",
                json={"platforms": {"bili": {"comment_page_interval": [1, 3]}}},
            )
            assert response.status_code == 200
            response = await client.patch(
                "/api/collect-settings",
                json={"platforms": {"bili": {"comment_page_interval": [0.5, 3]}}},
            )
            assert response.status_code == 422
            response = await client.patch(
                "/api/collect-settings", json={"platforms": {"bili": {"page_interval": [9, 4]}}}
            )
            assert response.status_code == 422
            fetcher.probe = AsyncMock(side_effect=ProfileInUse("占用"))
            response = await client.post("/api/platforms/bili/probe")
            assert response.status_code == 409 and response.json()["code"] == "PROFILE_IN_USE"
            assert (await client.post("/api/collect-settings/bili/reset")).status_code == 200
            async with db.sessionmaker() as session:
                assert await get_setting(session, "collect.rate_limits.bili") is None
    finally:
        await login.close()
        await db.close()


async def test_login_concurrent_and_shutdown(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    runtime = MagicMock()
    runtime.platforms = frozenset({"bili"})
    runtime.browser_kind.return_value = None
    entered = asyncio.Event()

    async def wait_login(platform, callback):
        callback("verifying")
        entered.set()
        await asyncio.Event().wait()
        return True

    runtime.login = wait_login
    login = LoginCoordinator(
        cast(PlatformRuntime, runtime),
        cast(CollectService, MagicMock()),
        db.sessionmaker,
        EventBus(),
    )
    try:
        login.start("bili")
        await entered.wait()
        assert login.status("bili").phase == "verifying"
        try:
            login.start("bili")
            raise AssertionError()
        except ApiError as error:
            assert error.body.code == "LOGIN_IN_PROGRESS"
        await login.close()
        assert login.tasks["bili"].cancelled()
    finally:
        await db.close()


async def test_login_success_warmup(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    runtime = MagicMock()
    runtime.platforms = frozenset({"bili"})
    runtime.browser_kind.return_value = None
    runtime.login = AsyncMock(return_value=True)
    runtime.warmup = AsyncMock()
    collect = MagicMock()
    collect.on_login_succeeded = AsyncMock()
    login = LoginCoordinator(
        cast(PlatformRuntime, runtime), cast(CollectService, collect), db.sessionmaker, EventBus()
    )
    try:
        login.start("bili")
        await login.tasks["bili"]
        collect.on_login_succeeded.assert_awaited_once_with("bili", 3)
        runtime.warmup.assert_awaited_once_with("bili", 3)
        assert login.status("bili").phase == "succeeded"
    finally:
        await login.close()
        await db.close()


async def test_warmup_failure_keeps_login_succeeded(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    runtime = MagicMock()
    runtime.platforms = frozenset({"bili"})
    runtime.browser_kind.return_value = None
    runtime.login = AsyncMock(return_value=True)
    runtime.warmup = AsyncMock(side_effect=RuntimeError("页面关了"))
    collect = MagicMock()
    collect.on_login_succeeded = AsyncMock()
    login = LoginCoordinator(
        cast(PlatformRuntime, runtime), cast(CollectService, collect), db.sessionmaker, EventBus()
    )
    try:
        login.start("bili")
        await login.tasks["bili"]
        assert login.status("bili").phase == "succeeded"
    finally:
        await login.close()
        await db.close()
