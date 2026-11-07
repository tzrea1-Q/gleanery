from pathlib import Path
from types import SimpleNamespace

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from gleanery.api.errors import ApiError
from gleanery.api.reports import router
from gleanery.events import EventBus
from gleanery.report import repo
from gleanery.store import Database, open_database
from gleanery.store.models import Content, ReportCitation
from tests.support.library import TZ


def make_app(db: Database) -> FastAPI:
    app = FastAPI()
    app.state.db = db
    app.state.deps = SimpleNamespace(clock=SimpleNamespace(now_ms=lambda: 2), tz=TZ)
    app.state.events = EventBus()
    app.include_router(router)

    @app.exception_handler(ApiError)
    async def handle_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body.model_dump())

    return app


async def test_report_endpoints(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    try:
        async with db.sessionmaker() as session:
            report = await repo.create(
                session,
                title="报告",
                markdown="原文",
                dataset_id=None,
                conversation_id=None,
                source="agent",
                now=1,
            )
            report_id = report.id
            await session.commit()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=make_app(db)), base_url="http://test"
        ) as client:
            url = f"/api/reports/{report_id}"
            assert (await client.get("/api/reports")).json()["total"] == 1
            assert (await client.get(url)).json()["markdown"] == "原文"
            saved = await client.put(
                url, json={"base_version": 1, "title": "新标题", "markdown": "[[c:999]]"}
            )
            assert saved.status_code == 200 and saved.json()["version"] == 2
            assert (
                await client.put(url, json={"base_version": 1, "title": "旧", "markdown": "旧"})
            ).json()["code"] == "VERSION_CONFLICT"
            revisions = (await client.get(url + "/revisions")).json()
            assert [item["version"] for item in revisions] == [2, 1]
            revision_url = url + f"/revisions/{revisions[1]['id']}"
            assert (await client.get(revision_url)).json()["markdown"] == "原文"
            restored = await client.post(revision_url + "/restore", json={"base_version": 2})
            assert restored.json()["version"] == 3 and restored.json()["markdown"] == "原文"
            assert (await client.get(url + "/revisions/999")).json()["code"] == "REVISION_NOT_FOUND"
            exported = await client.get(url + "/export")
            assert exported.status_code == 200
            assert exported.headers["content-type"] == "text/markdown; charset=utf-8"
            assert exported.text.startswith("# ")
            assert (await client.delete(url)).status_code == 204
            assert (await client.get(url)).json()["code"] == "REPORT_NOT_FOUND"
    finally:
        await db.close()


async def test_xhs_citation_links_carry_token(tmp_path: Path) -> None:
    note = "https://www.xiaohongshu.com/explore/6a315bf50000000015026a7a"
    opened = f"{note}?xsec_token=AB%3D&xsec_source=pc_search"
    db = await open_database(tmp_path)
    try:
        async with db.sessionmaker() as session:
            content = Content(
                platform="xhs",
                platform_id="6a315bf50000000015026a7a",
                url=note,
                kind="image_text",
                title="笔记",
                tags=[],
                completeness="detail",
                ext={"xsec_token": "AB=", "xsec_source": "pc_search"},
                created_at=1,
                updated_at=1,
            )
            session.add(content)
            await session.flush()
            content_id = content.id
            report = await repo.create(
                session,
                title="报告",
                markdown=f"正文[[c:{content_id}]]",
                dataset_id=None,
                conversation_id=None,
                source="agent",
                now=1,
            )
            report_id = report.id
            await session.commit()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=make_app(db)), base_url="http://test"
        ) as client:
            url = f"/api/reports/{report_id}"
            assert (await client.get(url)).json()["citations"][0]["url"] == opened
            assert opened in (await client.get(url + "/export")).text
            async with db.sessionmaker() as session:
                # 快照也是 Agent 读到的网址，不能带 token。
                snapshot = await session.scalar(select(ReportCitation))
                assert snapshot is not None and snapshot.url == note
                await session.delete(await session.get(Content, content_id))
                await session.commit()
            citation = (await client.get(url)).json()["citations"][0]
            assert citation["url"] == note and citation["deleted"] is True
    finally:
        await db.close()
