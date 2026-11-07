from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from gleanery.api.data_settings import router
from gleanery.events import EventBus
from gleanery.store.db import open_database
from tests.store.test_retention import seed


async def test_data_settings_endpoints(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    app = FastAPI()
    app.state.db = db
    app.state.deps = SimpleNamespace(
        data_dir=tmp_path, clock=SimpleNamespace(now_ms=lambda: 31 * 86400000)
    )
    app.state.events = EventBus()
    app.include_router(router)
    try:
        async with db.sessionmaker.begin() as session:
            await seed(session, [1, 31 * 86400000])
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/api/data-settings")).json()["raw_count"] == 2
            assert (
                await client.patch("/api/data-settings", json={"raw_retention_days": 8})
            ).status_code == 422
            response = await client.patch("/api/data-settings", json={"raw_retention_days": 7})
            assert response.status_code == 200, response.text
            assert response.json()["raw_count"] == 1
            assert (await client.post("/api/data-settings/purge-raw")).json() == {"deleted": 1}
            assert (
                await client.patch("/api/data-settings", json={"raw_retention_days": None})
            ).json()["raw_retention_days"] is None
            assert app.state.events._next_id == 4
    finally:
        await db.close()
