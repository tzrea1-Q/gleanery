from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gleanery.api.contents import router
from gleanery.api.errors import ApiError
from gleanery.store import open_database
from tests.support.library import SENTINEL, seed_library


async def test_detail_comments_and_locate(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        library = await seed_library(session)
    app = FastAPI()
    app.state.db = db
    app.include_router(router)

    @app.exception_handler(ApiError)
    async def handle_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body.model_dump())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        cid = library.contents["v1"]
        detail = (await client.get(f"/api/contents/{cid}")).json()
        assert SENTINEL in detail["body"] and SENTINEL in detail["subtitles"][0]["text"]
        comments = (await client.get(f"/api/contents/{cid}/comments?limit=1")).json()
        assert comments["total"] == 2 and comments["replies_total"] == 2
        assert [r["id"] for r in comments["items"][0]["replies"]] == [
            library.comments["r1"],
            library.comments["r2"],
        ]
        located = (await client.get(f"/api/comments/{library.comments['r2']}/locate")).json()
        assert located == {
            "content_id": cid,
            "root_comment_id": library.comments["c1"],
            "offset": 0,
        }
        located = (await client.get(f"/api/locate?content_id={library.contents['v3']}")).json()
        assert located["dataset_id"] == library.dataset_b
        assert (await client.get("/api/locate?content_id=99999")).status_code == 404
        assert (await client.get("/api/locate")).status_code == 400
    await db.close()
