from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gleanery.api.datasets import router
from gleanery.api.errors import ApiError
from gleanery.store import open_database, repo_datasets
from tests.support.library import TZ


async def test_dataset_endpoints(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        dataset = await repo_datasets.create_dataset(session, "测试", "说明", None, 1)
        dataset_id = dataset.id
        await session.commit()
    app = FastAPI()
    app.state.db = db
    app.state.deps = SimpleNamespace(tz=TZ)
    app.include_router(router)

    @app.exception_handler(ApiError)
    async def handle_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body.model_dump())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/datasets")).json()[0]["id"] == dataset_id
        assert (await client.get(f"/api/datasets/{dataset_id}")).json()["total"] == 0
        assert (await client.get(f"/api/datasets/{dataset_id}/contents")).json() == {
            "total": 0,
            "filtered_total": 0,
            "items": [],
        }
        assert (await client.get("/api/datasets/999/contents")).status_code == 404
        assert (await client.get(f"/api/datasets/{dataset_id}/contents?limit=0")).status_code == 422
    await db.close()
