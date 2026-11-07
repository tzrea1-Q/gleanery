from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from pydantic_ai import RunContext

from gleanery.agent.deps import AgentDeps
from gleanery.agent.tools.export import export_dataset
from gleanery.query.filters import ContentFilter
from gleanery.store import open_database
from tests.support.library import NOW, TZ, seed_library


async def test_export_tool(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        library = await seed_library(session)
    deps = SimpleNamespace(
        sessionmaker=db.sessionmaker, tz=TZ, clock=SimpleNamespace(now_ms=lambda: NOW)
    )
    ctx = cast(RunContext[AgentDeps], cast(Any, SimpleNamespace(deps=deps)))
    result = await export_dataset(
        ctx, library.dataset_a, "csv", filter=ContentFilter(keyword="耳机")
    )
    assert result["contents"] == 2 and result["filename"].endswith(".zip")
    assert parse_qs(urlsplit(result["download_url"]).query)["keyword"] == ["耳机"]
    assert (await export_dataset(ctx, 999, "md"))["error"]["code"] == "DATASET_NOT_FOUND"
    assert (await export_dataset(ctx, library.dataset_a, "md", comment_limit=-1))["error"][
        "code"
    ] == "INVALID_REQUEST"
    await db.close()
