import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select
from starlette.types import Message as ASGIMessage

from gleanery.app import create_app
from gleanery.clock import SystemClock
from gleanery.deps import AppDeps, ResolvedModel
from gleanery.store.models import Message
from tests.support.memory import MemoryCredentialStore


def client_for(tmp_path: Path, model: FunctionModel | None) -> TestClient:
    async def resolve(session):
        return ResolvedModel(model, "测试模型", 1) if model else None

    deps = AppDeps(tmp_path, "secret", 8765, SystemClock(), resolve, MemoryCredentialStore())
    client = TestClient(create_app(deps), base_url="http://127.0.0.1:8765")
    client.cookies.set("gleanery_session", "secret")
    client.headers["origin"] = "http://127.0.0.1:8765"
    return client


def payload(conversation_id: int, message_id: str, text: str) -> dict:
    return {
        "id": str(conversation_id),
        "trigger": "submit-message",
        "messages": [{"id": message_id, "role": "user", "parts": [{"type": "text", "text": text}]}],
    }


def test_chat_history_and_persistence(tmp_path: Path) -> None:
    seen: list[list[ModelMessage]] = []

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        seen.append(messages)
        yield "流式回复"

    with client_for(tmp_path, FunctionModel(stream_function=stream)) as client:
        cid = client.post("/api/conversations").json()["id"]
        response = client.post("/api/chat", json=payload(cid, "one", "  第一行\n第二行  "))
        assert response.status_code == 200 and "流式回复" in response.text
        detail = client.get(f"/api/conversations/{cid}").json()
        assert detail["title"] == "第一行 第二行"
        assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
        assert detail["messages"][1]["metadata"]["model"] == "测试模型"
        assert client.post("/api/chat", json=payload(cid, "two", "再问")).status_code == 200
        assert len(seen[1]) >= 3

        async def check_rows():
            async with cast(FastAPI, client.app).state.db.sessionmaker() as session:
                return list(await session.scalars(select(Message).order_by(Message.seq)))

        assert client.portal is not None
        rows = client.portal.call(check_rows)
        assert [row.seq for row in rows] == [0, 1, 2, 3]
        assert [row.model_name for row in rows] == [None, "测试模型", None, "测试模型"]


def test_no_model(tmp_path: Path) -> None:
    with client_for(tmp_path, None) as client:
        cid = client.post("/api/conversations").json()["id"]
        response = client.post("/api/chat", json=payload(cid, "one", "你好"))
        assert (response.status_code, response.json()["code"]) == (409, "NO_MODEL")
        assert client.post("/api/chat", json=payload(999, "one", "你好")).status_code == 404


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "MODEL_AUTH_FAILED"),
        (403, "MODEL_AUTH_FAILED"),
        (429, "MODEL_RATE_LIMITED"),
        (500, "MODEL_ERROR"),
    ],
)
def test_model_failure(tmp_path: Path, status: int, code: str) -> None:
    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        raise ModelHTTPError(status_code=status, model_name="test")
        yield ""

    with (
        client_for(tmp_path, FunctionModel(stream_function=stream)) as client,
        patch("gleanery.api.chat.mark_config_status", new_callable=AsyncMock) as hook,
    ):
        cid = client.post("/api/conversations").json()["id"]
        response = client.post("/api/chat", json=payload(cid, "one", "你好"))
        chunks = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: {")
        ]
        error = next(chunk for chunk in chunks if chunk["type"] == "error")
        assert json.loads(error["errorText"])["code"] == code
        assert hook.call_count == (1 if status in (401, 403) else 0)
        assert [m["role"] for m in client.get(f"/api/conversations/{cid}").json()["messages"]] == [
            "user"
        ]


def test_retry_after_failure_does_not_duplicate_user(tmp_path: Path) -> None:
    attempts = 0

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ModelHTTPError(status_code=401, model_name="test")
        yield "成功"

    with client_for(tmp_path, FunctionModel(stream_function=stream)) as client:
        cid = client.post("/api/conversations").json()["id"]
        request = payload(cid, "one", "你好")
        client.post("/api/chat", json=request)
        assert "成功" in client.post("/api/chat", json=request).text
        messages = client.get(f"/api/conversations/{cid}").json()["messages"]
        assert [message["role"] for message in messages] == ["user", "assistant"]


def test_regenerate_replaces_previous_reply(tmp_path: Path) -> None:
    replies = iter(["第一次回复", "重新生成的回复"])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        yield next(replies)

    with client_for(tmp_path, FunctionModel(stream_function=stream)) as client:
        cid = client.post("/api/conversations").json()["id"]
        client.post("/api/chat", json=payload(cid, "one", "你好"))
        first = client.get(f"/api/conversations/{cid}").json()["messages"]
        regenerate = {
            **payload(cid, "one", "你好"),
            "trigger": "regenerate-message",
            "messageId": first[1]["id"],
        }
        assert "重新生成的回复" in client.post("/api/chat", json=regenerate).text
        messages = client.get(f"/api/conversations/{cid}").json()["messages"]
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert "重新生成的回复" in json.dumps(messages[1], ensure_ascii=False)
        assert "第一次回复" not in json.dumps(messages, ensure_ascii=False)


def test_client_disconnect_keeps_run_and_saves_reply(tmp_path: Path) -> None:
    """切到别的对话会断开流；这一轮要在后台跑完并落库，否则已执行的工具（如开始采集）没有记录。"""
    gate: dict[str, asyncio.Event] = {}
    calls: list[int] = []

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        calls.append(1)
        yield "开头"
        if len(calls) == 1:
            await gate["release"].wait()
        yield "结尾"

    with client_for(tmp_path, FunctionModel(stream_function=stream)) as client:
        app = cast(FastAPI, client.app)
        cid = client.post("/api/conversations").json()["id"]
        body = json.dumps(payload(cid, "one", "你好")).encode()

        async def send_then_disconnect() -> None:
            gate["release"] = asyncio.Event()
            started = asyncio.Event()
            requested = False

            async def receive() -> ASGIMessage:
                nonlocal requested
                if not requested:
                    requested = True
                    return {"type": "http.request", "body": body, "more_body": False}
                await started.wait()
                return {"type": "http.disconnect"}

            async def send(message: ASGIMessage) -> None:
                if "开头" in message.get("body", b"").decode(errors="ignore"):
                    started.set()

            scope = {
                "type": "http",
                "method": "POST",
                "path": "/api/chat",
                "raw_path": b"/api/chat",
                "query_string": b"",
                "scheme": "http",
                "server": ("127.0.0.1", 8765),
                "client": ("127.0.0.1", 50000),
                "headers": [
                    (b"host", b"127.0.0.1:8765"),
                    (b"origin", b"http://127.0.0.1:8765"),
                    (b"cookie", b"gleanery_session=secret"),
                    (b"content-type", b"application/json"),
                ],
            }
            await app(scope, receive, send)

        async def finish() -> None:
            gate["release"].set()
            for _ in range(200):
                if app.state.runs.busy(cid) is None:
                    return
                await asyncio.sleep(0.01)

        assert client.portal is not None
        client.portal.call(send_then_disconnect)
        busy = client.post("/api/chat", json=payload(cid, "two", "再问"))
        assert busy.status_code == 409 and busy.json()["code"] == "CONVERSATION_BUSY"
        client.portal.call(finish)
        messages = client.get(f"/api/conversations/{cid}").json()["messages"]
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert "开头结尾" in json.dumps(messages[1], ensure_ascii=False)
