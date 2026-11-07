import asyncio
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.models.anthropic import AnthropicModel

from gleanery.app import create_app
from gleanery.clock import SystemClock
from gleanery.deps import AppDeps
from gleanery.llm.credentials import FileCredentialStore
from gleanery.llm.resolver import make_model_resolver
from tests.support.fake_anthropic import fake_anthropic


def test_配置分页工具调用和解析(tmp_path: Path) -> None:
    server = fake_anthropic()
    transport = httpx2.ASGITransport(app=server)
    store = FileCredentialStore(tmp_path)
    resolver = make_model_resolver(store, transport)
    deps = AppDeps(
        data_dir=tmp_path,
        launch_token="session",
        port=8765,
        clock=SystemClock(),
        credential_store=store,
        model_resolver=resolver,
        llm_transport=transport,
    )
    app = create_app(deps)
    with (
        TestClient(
            app,
            base_url="http://127.0.0.1:8765",
            headers={"origin": "http://127.0.0.1:8765"},
            cookies={"gleanery_session": "session"},
        ) as client,
        override_allow_model_requests(True),
    ):
        preset = next(p for p in client.get("/api/model-presets").json() if p["id"] == "anthropic")
        assert (
            preset["kind"],
            preset["api_style"],
            preset["base_url"],
            preset["key_required"],
        ) == ("anthropic", "messages", "https://api.anthropic.com", True)
        response = client.post(
            "/api/model-configs",
            json={
                "name": "测试",
                "preset": "anthropic",
                "base_url": "http://custom",
                "api_key": "test-key",
            },
        )
        assert response.status_code == 201 and "test-key" not in response.text
        config = response.json()
        assert (config["kind"], config["preset"], config["status"]) == (
            "anthropic",
            "anthropic",
            "ok",
        )
        assert config["available_models"] == ["model-1", "model-2"]
        assert config["model_labels"] == {"model-1": "模型一", "model-2": "模型二"}
        favorite = client.post(
            f"/api/model-configs/{config['id']}/favorites", json={"model": "model-1"}
        ).json()
        assert favorite["favorites"][0]["tool_test"] == "ok", favorite["favorites"][0][
            "tool_test_error"
        ]
        assert (
            client.put(
                "/api/app-state/current-model", json={"config_id": config["id"], "model": "model-1"}
            ).status_code
            == 200
        )

        async def resolve():
            async with app.state.db.sessionmaker() as session:
                return await resolver(session)

        resolved = asyncio.run(resolve())
        assert resolved is not None and isinstance(resolved.model, AnthropicModel)
        request, body = server.state.requests[-1]
        assert str(request.url).startswith("http://custom/v1/messages")
        assert "temperature" not in body


@pytest.mark.parametrize(
    ("status", "no_tool", "missing", "key", "expected", "reason"),
    [
        (401, False, False, "wrong", "unavailable", "凭证无效"),
        (429, False, False, "test-key", "unavailable", "上游 429"),
        (200, True, False, "test-key", "ok", None),
        (200, False, True, "test-key", "ok", None),
    ],
)
def test_错误和工具调用失败(
    tmp_path: Path,
    status: int,
    no_tool: bool,
    missing: bool,
    key: str,
    expected: str,
    reason: str | None,
) -> None:
    transport = httpx2.ASGITransport(app=fake_anthropic(status, no_tool, missing))
    store = FileCredentialStore(tmp_path)
    deps = AppDeps(
        data_dir=tmp_path,
        launch_token="session",
        port=8765,
        clock=SystemClock(),
        credential_store=store,
        model_resolver=make_model_resolver(store, transport),
        llm_transport=transport,
    )
    with (
        TestClient(
            create_app(deps),
            base_url="http://127.0.0.1:8765",
            headers={"origin": "http://127.0.0.1:8765"},
            cookies={"gleanery_session": "session"},
        ) as client,
        override_allow_model_requests(True),
    ):
        response = client.post(
            "/api/model-configs",
            json={"name": "测试", "preset": "anthropic", "base_url": "http://fake", "api_key": key},
        )
        config = response.json()
        assert key not in response.text
        assert (config["status"], config["status_reason"]) == (expected, reason)
        if missing:
            assert config["available_models"] is None
        result = client.post(
            f"/api/model-configs/{config['id']}/favorites", json={"model": "model-1"}
        ).json()
        assert result["favorites"][0]["tool_test"] == ("ok" if missing else "failed")


def test_连接失败(tmp_path: Path) -> None:
    class Broken(httpx2.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("failed", request=request)

    transport = Broken()
    store = FileCredentialStore(tmp_path)
    deps = AppDeps(
        data_dir=tmp_path,
        launch_token="session",
        port=8765,
        clock=SystemClock(),
        credential_store=store,
        model_resolver=make_model_resolver(store, transport),
        llm_transport=transport,
    )
    with TestClient(
        create_app(deps),
        base_url="http://127.0.0.1:8765",
        headers={"origin": "http://127.0.0.1:8765"},
        cookies={"gleanery_session": "session"},
    ) as client:
        config = client.post(
            "/api/model-configs",
            json={
                "name": "测试",
                "preset": "anthropic",
                "base_url": "http://fake",
                "api_key": "test-key",
            },
        ).json()
        assert (config["status"], config["status_reason"], config["available_models"]) == (
            "unavailable",
            "连接失败",
            None,
        )
