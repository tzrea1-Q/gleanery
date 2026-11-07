import csv
import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from gleanery.export.rows import load
from gleanery.export.writers import csv_zip, markdown, xlsx
from gleanery.query.filters import ContentFilter
from gleanery.store import open_database
from tests.support.library import NOW, TZ, seed_library


async def test_export_formats(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        library = await seed_library(session)
        data = await load(session, library.dataset_b, None, "added_desc", TZ)
        assert data is not None
        next(c for c, _ in data.contents if c.id == library.contents["v4"]).body = (
            "=1+1" + "字" * 33000
        )
        workbook = zipfile.ZipFile(io.BytesIO(xlsx(data, TZ, NOW, None, False)))
        strings = workbook.read("xl/sharedStrings.xml").decode()
        sheet = workbook.read("xl/worksheets/sheet1.xml").decode()
        assert "内容 ID" in strings and "=1+1" in strings and "已截断，见 Markdown 导出" in strings
        assert "<f>" not in sheet
        root = ElementTree.fromstring(strings)
        texts = ["".join(item.itertext()) for item in root]
        truncated = next(text for text in texts if text.startswith("=1+1"))
        assert len(truncated) == 32767
        assert "yyyy-mm-dd hh:mm" in workbook.read("xl/styles.xml").decode()
        assert "xl/workbook.xml" in workbook.namelist()
        archive = zipfile.ZipFile(io.BytesIO(csv_zip(data, TZ, False)))
        assert set(archive.namelist()) == {"内容.csv", "评论.csv", "字幕.csv"}
        for name in archive.namelist():
            assert archive.read(name).startswith(b"\xef\xbb\xbf")
        content = archive.read("内容.csv").decode("utf-8-sig")
        assert "'=1+1" in content and "\r\n" in content
        assert next(iter(csv.reader(io.StringIO(content))))[0] == "内容 ID"
        filtered = await load(
            session, library.dataset_a, ContentFilter(keyword="耳机"), "likes_desc", TZ
        )
        assert filtered is not None and len(filtered.contents) == 2
        md = markdown(filtered, TZ, NOW, None, 20, True).decode()
        assert "≈1000" in md and "\n  - " in md and "2026-10-01 10:00:00" in md
        assert "导出时间：" in md and "（UTC+08:00）" in md
        root = next(x for x in filtered.comments if x.root_platform_id is None)
        root.body = "第一行\n\n- 第二行\n2. 第三行"
        md = markdown(filtered, TZ, NOW, None, 20, True).decode()
        assert "：第一行\n  \\- 第二行\n  2\\. 第三行\n" in md
    await db.close()


async def test_xhs_links_carry_token(tmp_path: Path) -> None:
    note = "https://www.xiaohongshu.com/explore/6a315bf50000000015026a7a"
    opened = f"{note}?xsec_token=AB%3D&xsec_source=pc_search"
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        library = await seed_library(session)
        data = await load(session, library.dataset_b, None, "added_desc", TZ)
        assert data is not None
        content = next(c for c, _ in data.contents if c.id == library.contents["v4"])
        content.platform, content.url = "xhs", note
        content.ext = {"xsec_token": "AB=", "xsec_source": "pc_search"}
        workbook = zipfile.ZipFile(io.BytesIO(xlsx(data, TZ, NOW, None, False)))
        assert opened.replace("&", "&amp;") in workbook.read("xl/sharedStrings.xml").decode()
        archive = zipfile.ZipFile(io.BytesIO(csv_zip(data, TZ, False)))
        assert opened in archive.read("内容.csv").decode("utf-8-sig")
        assert f"原文链接：{opened}\n" in markdown(data, TZ, NOW, None, 20, False).decode()
    await db.close()


async def test_export_api(tmp_path: Path) -> None:
    from types import SimpleNamespace

    import httpx
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    from gleanery.api.errors import ApiError
    from gleanery.api.exports import router

    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        library = await seed_library(session)
    app = FastAPI()
    app.state.db = db
    app.state.deps = SimpleNamespace(tz=TZ, clock=SimpleNamespace(now_ms=lambda: NOW))
    app.include_router(router)

    @app.exception_handler(ApiError)
    async def handle_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body.model_dump())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/datasets/{library.dataset_a}/export", params={"format": "md", "keyword": "耳机"}
        )
        assert response.status_code == 200
        assert "filename*=UTF-8''" in response.headers["content-disposition"]
        assert "内容：2 条" in response.text
        assert (await client.get("/api/datasets/999/export?format=xlsx")).status_code == 404
        assert (
            await client.get(
                f"/api/datasets/{library.dataset_a}/export?format=md&comment_limit=201"
            )
        ).status_code == 422
    await db.close()
