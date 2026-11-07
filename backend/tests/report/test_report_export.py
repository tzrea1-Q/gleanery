from zoneinfo import ZoneInfo

from gleanery.api.schemas_reports import CitationOut, ReportBasis, ReportDetail
from gleanery.report.export import render_markdown


def test_render_markdown() -> None:
    citation = CitationOut(
        kind="content",
        target_id=1,
        content_id=1,
        platform="bili",
        excerpt="标题",
        author="作者",
        url="https://example.com",
        saved_at=0,
        deleted=True,
    )
    report = ReportDetail(
        id=1,
        title="报告",
        version=2,
        dataset_id=1,
        dataset_name="咖啡",
        created_in_conversation_id=None,
        conversation_title=None,
        created_at=0,
        updated_at=0,
        updated_by="user",
        markdown="# 报告\n\n引用 [[c:1]] 和 [[c:1]]",
        basis=ReportBasis(dataset_name="咖啡", contents=3, comments=4, recorded_at=0),
        new_since=0,
        citations=[citation],
    )
    text = render_markdown(report, report.citations, 0, ZoneInfo("Asia/Shanghai"))
    assert text.count("# 报告") == 1
    assert "基于 3 条内容、4 条评论 · 数据集「咖啡」" in text
    assert "1970-01-01 08:00:00" in text and "1970-01-01T08:00+08:00" in text
    assert "引用 [^1] 和 [^1]" in text
    assert "[^1]: B 站 · 标题 · 作者 · https://example.com · 已从内容库删除" in text
    report.dataset_id = None
    assert "未关联数据集" in render_markdown(report, [], 0, ZoneInfo("Asia/Shanghai"))


async def test_export_filename(tmp_path) -> None:
    from types import SimpleNamespace

    import httpx
    from fastapi import FastAPI

    from gleanery.api.reports import router
    from gleanery.report import repo
    from gleanery.store import open_database

    db = await open_database(tmp_path)
    try:
        async with db.sessionmaker() as session:
            report = await repo.create(
                session,
                title='报告/\\:*?"<>|\n名',
                markdown="正文",
                dataset_id=None,
                conversation_id=None,
                source="agent",
                now=0,
            )
            report_id = report.id
            await session.commit()
        app = FastAPI()
        app.state.db = db
        app.state.deps = SimpleNamespace(
            clock=SimpleNamespace(now_ms=lambda: 0), tz=ZoneInfo("Asia/Shanghai")
        )
        app.include_router(router)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/api/reports/{report_id}/export")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/markdown; charset=utf-8"
        assert (
            response.headers["content-disposition"]
            == f"""attachment; filename="report-{report_id}.md"; filename*=UTF-8''%E6%8A%A5%E5%91%8A__________%E5%90%8D-19700101.md"""
        )
    finally:
        await db.close()
