from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gleanery.api.errors import ApiError
from gleanery.api.plans import router
from gleanery.events import EventBus
from gleanery.store import open_database, repo_plans
from tests.agent.test_plan_tools import FakeClock, FakeCollect, body


class WaitingCollect(FakeCollect):
    """平台还在任务间隔内，额度也不够：起草时要提示的两种情况。"""

    async def quota_remaining(self, session, platform) -> int:  # pyright: ignore[reportIncompatibleMethodOverride]
        return 0

    async def platform_view(self, session, platform):
        view = await super().platform_view(session, platform)
        return view.model_copy(update={"wait_reason": "min_interval"})


async def test_plan_patch_conflict_and_lock(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        plan = await repo_plans.create_draft(session, None, body(), 1)
        plan_id = plan.id
        await session.commit()
    app = FastAPI()
    app.state.db = db
    app.state.deps = SimpleNamespace(clock=FakeClock())
    app.state.collect = FakeCollect()
    app.state.events = EventBus()
    app.include_router(router)

    @app.exception_handler(ApiError)
    async def handle_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body.model_dump())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        payload = {"base_version": 1, "body": body(2).model_dump(mode="json")}
        result = await client.patch(f"/api/plans/{plan_id}", json=payload)
        assert result.status_code == 200 and result.json()["version"] == 2
        result = await client.patch(f"/api/plans/{plan_id}", json=payload)
        assert result.status_code == 409 and result.json()["code"] == "VERSION_CONFLICT"
        async with db.sessionmaker() as session:
            plan = await repo_plans.get(session, plan_id)
            assert plan is not None
            plan.status = "confirmed"
            await session.commit()
        result = await client.patch(f"/api/plans/{plan_id}", json=payload)
        assert result.status_code == 409 and result.json()["code"] == "PLAN_LOCKED"
    await db.close()


async def test_readiness_hints_only_apply_to_plans_not_started(tmp_path: Path) -> None:
    """计划确认后任务已经建好，等待原因由任务进度显示；这里的提示是起草时的状态，会过期。"""
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        plan = await repo_plans.create_draft(session, None, body(), 1)
        plan_id = plan.id
        await session.commit()
    app = FastAPI()
    app.state.db = db
    app.state.deps = SimpleNamespace(clock=FakeClock())
    app.state.collect = WaitingCollect()
    app.state.events = EventBus()
    app.include_router(router)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        draft = (await client.get(f"/api/plans/{plan_id}")).json()
        assert {issue["code"] for issue in draft["issues"]} == {
            "QUOTA_EXCEEDED",
            "PLATFORM_NOT_READY",
        }
        assert "距上个任务的间隔还不够" in " ".join(item["message"] for item in draft["issues"])
        async with db.sessionmaker() as session:
            plan = await repo_plans.get(session, plan_id)
            assert plan is not None
            plan.status = "confirmed"
            await session.commit()
        confirmed = (await client.get(f"/api/plans/{plan_id}")).json()
        assert confirmed["status"] == "confirmed" and confirmed["issues"] == []
    await db.close()
