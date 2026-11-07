import json
from pathlib import Path
from typing import Any

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from gleanery.agent import build_agent
from gleanery.query import agent as query
from gleanery.store import open_database
from gleanery.store.models import Comment
from tests.support.agent import agent_deps
from tests.support.library import SENTINEL, TZ, seed_library


def strip_untrusted(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: strip_untrusted(v) for k, v in value.items() if k != "untrusted"}
    if isinstance(value, list):
        return [strip_untrusted(v) for v in value]
    return value


async def test_queries_and_model_roundtrip(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        library = await seed_library(session)
        results = [
            await query.query_contents(session, TZ, library.dataset_a, None, "likes_desc", 20, 0),
            await query.get_content(
                session, TZ, library.contents["v1"], 50, "likes", True, True, 4000
            ),
            await query.query_comments(
                session, TZ, library.dataset_a, None, None, None, True, "likes", 30, 0
            ),
            await query.aggregate(session, TZ, library.dataset_a, "author", "likes", None),
        ]
        invalid = await query.query_contents(
            session, TZ, library.dataset_a, None, "likes_desc", 51, 0
        )
        assert invalid["error"]["code"] == "INVALID_REQUEST"
        comment = await session.get(Comment, library.comments["c1"])
        assert comment is not None
        comment.body = "长" * 301
        await session.flush()
        long_result = await query.query_comments(
            session, TZ, None, library.contents["v1"], None, None, True, "likes", 30, 0
        )
        assert (
            long_result["items"][0]["truncated"]
            and len(long_result["items"][0]["untrusted"]["body"]) == 301
        )
        assert results[0]["total"] == 3
        assert results[0]["items"][0]["published_at"] == "2026-10-01T10:00+08:00"
        assert results[1]["comments_total"] == 2 and results[1]["replies_total"] == 2
        assert results[2]["total"] == 5
        mentions = await query.count_mentions(
            session, TZ, library.dataset_a, ["续航|夹头"], "both", None
        )
        assert mentions["items"][0]["contents"] == 2 and mentions["items"][0]["comments"] == 2
        for item in results:
            assert SENTINEL in json.dumps(item, ensure_ascii=False)
            assert SENTINEL not in json.dumps(strip_untrusted(item), ensure_ascii=False)
    seen = []

    def respond(messages, info):
        parts = [p for p in messages[-1].parts if isinstance(p, ToolReturnPart)]
        if parts:
            seen.append(parts[0].content)
            return ModelResponse(parts=[TextPart("完成")])
        return ModelResponse(
            parts=[
                ToolCallPart("query_contents", {"dataset_id": library.dataset_a}, tool_call_id="1")
            ]
        )

    deps = agent_deps(db, tmp_path, collect=None, clock=None)
    result = await build_agent().run("查询", model=FunctionModel(respond), deps=deps)
    assert result.output == "完成" and seen[0]["total"] == 3
    await db.close()
