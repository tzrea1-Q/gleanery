from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gleanery.api.errors import ApiError
from gleanery.api.tasks import router
from gleanery.collect.plan import PlatformSection
from gleanery.platforms.types import Depth
from tests.collect.test_worker_scenarios import setup


async def test_tasks_api(tmp_path: Path) -> None:
    section = PlatformSection(platform="bili", targets=["a"], quantity=0, depth=Depth())
    db, service, _, _ = await setup(tmp_path, section, ["a"])
    app = FastAPI()
    app.state.db = db
    app.state.collect = service
    app.include_router(router)

    @app.exception_handler(ApiError)
    async def handle_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body.model_dump())

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert len((await client.get("/api/tasks")).json()) == 1
            assert (await client.get("/api/tasks/999")).status_code == 404
            assert (await client.post("/api/tasks/1/resume")).status_code == 409
            assert (await client.post("/api/tasks/1/pause")).json()["status"] == "paused"
            assert (await client.post("/api/tasks/1/resume")).json()["status"] == "queued"
            assert (await client.post("/api/tasks/1/stop")).json()["status"] == "stopped"
    finally:
        await db.close()
