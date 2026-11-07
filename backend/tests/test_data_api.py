from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gleanery.api.data import router as data_router
from gleanery.api.datasets import router as datasets_router
from gleanery.api.errors import ApiError
from gleanery.collect.plan_check import check
from gleanery.events import EventBus
from gleanery.store import cleanup, open_database, repo_plans
from gleanery.store.models import (
    CollectionTask,
    Conversation,
    ModelConfig,
    PlatformState,
    RiskEvent,
    Setting,
)
from tests.agent.test_plan_tools import FakeCollect, body
from tests.support.library import seed_library


async def test_stop_before_delete_and_clear(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        lib = await seed_library(session)
        task = CollectionTask(
            dataset_id=lib.dataset_a,
            platform="bili",
            status="paused",
            queue_key=0,
            snapshot={},
            progress={},
            created_at=1,
            updated_at=1,
        )
        session.add(task)
        plan_body = body().model_copy(update={"target_dataset_id": lib.dataset_a})
        plan = await repo_plans.create_draft(session, None, plan_body, 1)
        plan.target_dataset_id = lib.dataset_a
        session.add_all(
            [
                Conversation(id=10, title="保留", created_at=1, updated_at=1),
                Setting(key="保留", value={"v": 1}),
                PlatformState(platform="bili", state="normal", updated_at=1),
                ModelConfig(
                    id=1,
                    kind="llm",
                    name="模型",
                    preset="custom",
                    base_url="",
                    api_style="chat",
                    status="ready",
                    favorites=[],
                    created_at=1,
                    updated_at=1,
                ),
            ]
        )
        await session.flush()
        session.add(
            RiskEvent(
                at=1,
                platform="bili",
                signal="test",
                signal_type="status",
                task_id=task.id,
                collected_count=0,
                rate_params={},
                outcome="cooldown",
            )
        )
        await session.commit()
        task_id, plan_id = task.id, plan.id

    class StoppingCollect(FakeCollect):
        async def stop_tasks(self, *, task_id=None, plan_id=None):
            async with db.sessionmaker() as session:
                task = await session.get(CollectionTask, task_id)
                assert task is not None and task.status == "paused"
                task.status = "stopped"
                await session.commit()
            return []

    app = FastAPI()
    app.state.db, app.state.events, app.state.collect = db, EventBus(), StoppingCollect()
    app.include_router(datasets_router)
    app.include_router(data_router)

    @app.exception_handler(ApiError)
    async def handle_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body.model_dump())

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/data/clear", json={})
            assert response.status_code == 409
            response = await client.delete(f"/api/datasets/{lib.dataset_a}")
            assert (
                response.status_code == 409
                and response.json()["code"] == "DATASET_HAS_ACTIVE_TASKS"
            )
            response = await client.delete(f"/api/datasets/{lib.dataset_a}?stop_active=true")
            assert response.status_code == 200 and response.json()["recycled_contents"] == 2
            async with db.sessionmaker() as session:
                assert await session.get(CollectionTask, task_id) is None
                plan = await repo_plans.get(session, plan_id)
                assert plan is not None and plan.target_dataset_id is None
                issues, _ = await check(session, plan_body, app.state.collect, 1)
                assert any(issue.code == "DATASET_NOT_FOUND" for issue in issues)
            async with db.sessionmaker() as session:
                session.add(
                    CollectionTask(
                        dataset_id=lib.dataset_b,
                        platform="bili",
                        status="paused",
                        queue_key=0,
                        snapshot={},
                        progress={},
                        created_at=1,
                        updated_at=1,
                    )
                )
                await session.commit()
            response = await client.post("/api/data/clear", json={"stop_active": True})
            assert response.status_code == 200 and response.json()["datasets"] == 1
            async with db.sessionmaker() as session:
                assert (await cleanup.impact_of_all(session)).contents == 0
                assert await repo_plans.get(session, plan_id) is not None
                assert await session.get(Conversation, 10) is not None
                assert await session.get(Setting, "保留") is not None
                assert await session.get(ModelConfig, 1) is not None
                assert await session.get(PlatformState, "bili") is not None
                risk = await session.get(RiskEvent, 1)
                assert risk is not None and risk.task_id is None
    finally:
        await db.close()
