from pathlib import Path
from typing import cast
from unittest.mock import patch

from fastapi import FastAPI
from sqlalchemy import func, select

from gleanery.events import EventBus
from gleanery.store.models import Message
from tests.test_chat import client_for, payload


def test_delete_cascades_and_publishes(tmp_path: Path) -> None:
    from collections.abc import AsyncIterator

    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        yield "回复"

    with client_for(tmp_path, FunctionModel(stream_function=stream)) as client:
        with patch.object(EventBus, "publish", autospec=True) as publish:
            cid = client.post("/api/conversations").json()["id"]
            client.post("/api/chat", json=payload(cid, "one", "你好"))
            assert client.delete(f"/api/conversations/{cid}").status_code == 204
            assert client.get(f"/api/conversations/{cid}").status_code == 404
            assert client.delete(f"/api/conversations/{cid}").status_code == 404
            assert any(
                call.args[1:] == ("conversation.deleted", {"conversation_id": cid})
                for call in publish.call_args_list
            )
            assert any(
                call.args[1:] == ("conversation.updated", {"conversation_id": cid})
                for call in publish.call_args_list
            )

        async def count():
            async with cast(FastAPI, client.app).state.db.sessionmaker() as session:
                return await session.scalar(select(func.count()).select_from(Message))

        assert client.portal is not None
        assert client.portal.call(count) == 0


def test_history_pairs_tool_calls_with_results(tmp_path: Path) -> None:
    """刷新后工具卡片要拿到结果：调用与结果分在两条消息里，转换时要配上对。"""
    from collections.abc import AsyncIterator

    from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart
    from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel

    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | DeltaToolCalls]:
        last = messages[-1]
        if isinstance(last, ModelRequest) and any(
            isinstance(part, ToolReturnPart) for part in last.parts
        ):
            yield "共有 0 个数据集"
        else:
            yield {0: DeltaToolCall("list_datasets", "{}", tool_call_id="call-1")}

    with client_for(tmp_path, FunctionModel(stream_function=stream)) as client:
        cid = client.post("/api/conversations").json()["id"]
        client.post("/api/chat", json=payload(cid, "one", "有哪些数据集"))
        messages = client.get(f"/api/conversations/{cid}").json()["messages"]
    tools = [part for m in messages for part in m["parts"] if part["type"] == "tool-list_datasets"]
    assert [part["state"] for part in tools] == ["output-available"]
    assert tools[0]["output"]["total"] == 0
    assert all(m["metadata"] == {"model": "测试模型"} for m in messages if m["role"] == "assistant")


def test_workspace_open_report_is_stored(tmp_path: Path) -> None:
    from gleanery.store.repo_settings import get_setting

    with client_for(tmp_path, None) as client:
        cid = client.post("/api/conversations").json()["id"]
        url = f"/api/conversations/{cid}/workspace"
        assert client.put(url, json={"report_id": 7}).json() == {"report_id": 7}
        assert (
            client.put("/api/conversations/999/workspace", json={"report_id": 7}).status_code == 404
        )

        async def stored():
            async with cast(FastAPI, client.app).state.db.sessionmaker() as session:
                return await get_setting(session, f"workspace.open_report.{cid}")

        assert client.portal is not None
        assert client.portal.call(stored) == 7
        client.put(url, json={"report_id": None})
        assert client.portal.call(stored) is None
