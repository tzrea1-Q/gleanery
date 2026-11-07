from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2
import pydantic_ai.providers.openai_chatgpt as oauth
import pytest
from fastapi.testclient import TestClient

from gleanery.app import create_app
from gleanery.clock import SystemClock
from gleanery.deps import AppDeps
from gleanery.llm.chatgpt import ChatGPTPlan
from gleanery.llm.credentials import FileCredentialStore
from gleanery.llm.resolver import make_model_resolver
from tests.support.fake_siwc import FakeSIWC


def test_连接断开删除与声明(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSIWC()
    transport = httpx2.ASGITransport(app=fake.app)
    original = vars(oauth)["_post_token_request"]

    async def exchange(*args, **kwargs):
        if kwargs.get("http_client") is not None:
            return await original(*args, **kwargs)
        async with httpx2.AsyncClient(transport=transport) as client:
            return await original(*args, **kwargs, http_client=client)

    monkeypatch.setattr(oauth, "_post_token_request", exchange)
    store = FileCredentialStore(tmp_path)
    clock = SystemClock()
    plan = ChatGPTPlan(store, clock, 8765, transport)
    deps = AppDeps(
        tmp_path,
        "session",
        8765,
        clock,
        make_model_resolver(store, transport, plan),
        store,
        llm_transport=transport,
        chatgpt=plan,
    )
    with TestClient(
        create_app(deps),
        base_url="http://127.0.0.1:8765",
        headers={"origin": "http://127.0.0.1:8765"},
        cookies={"gleanery_session": "session"},
    ) as client:
        assert (
            client.post(
                "/api/model-configs",
                json={"name": "x", "preset": "chatgpt", "base_url": "https://api.openai.com/v1"},
            ).json()["code"]
            == "INVALID_PRESET"
        )
        assert client.post("/api/chatgpt/disconnect").status_code == 404
        redirect = client.get("/api/chatgpt/connect", follow_redirects=False)
        assert redirect.status_code == 303
        query = parse_qs(urlsplit(redirect.headers["location"]).query)
        fake.challenge, fake.nonce = query["code_challenge"][0], query["nonce"][0]
        callback = client.get(
            "/auth/callback",
            params={
                "state": query["state"][0],
                "code": "secret-code",
                "client_id": "oaiapp_test",
                "untrusted": "secret-text",
            },
        )
        assert callback.status_code == 200 and "已连接" in callback.text
        assert "secret" not in callback.text
        assert client.get("/auth/callback", params={"state": query["state"][0]}).status_code == 400
        config = client.get("/api/model-configs").json()[0]
        config_id = config["id"]
        assert config["has_credential"] and config["available_models"] == ["fake-model"]
        assert (
            client.patch(f"/api/model-configs/{config_id}", json={"name": "改名"}).json()["name"]
            == "改名"
        )
        assert (
            client.patch(f"/api/model-configs/{config_id}", json={"api_key": "x"}).status_code
            == 400
        )
        assert client.post("/api/app-state/chatgpt-notice-ack").json()[
            "chatgpt_notice_acknowledged"
        ]
        disconnected = client.post("/api/chatgpt/disconnect").json()
        assert disconnected["status"] == "needs_reconnect" and not disconnected["has_credential"]
        assert fake.revocations == 1
        assert client.delete(f"/api/model-configs/{config_id}").status_code == 204
        assert store.get(config_id) is None


def test_未装配时返回不可用(tmp_path: Path) -> None:
    store = FileCredentialStore(tmp_path)
    deps = AppDeps(tmp_path, "session", 8765, SystemClock(), make_model_resolver(store), store)
    with TestClient(
        create_app(deps),
        base_url="http://127.0.0.1:8765",
        headers={"origin": "http://127.0.0.1:8765"},
        cookies={"gleanery_session": "session"},
    ) as client:
        for method, path in [
            ("get", "/api/chatgpt/connect"),
            ("post", "/api/chatgpt/disconnect"),
            ("get", "/auth/callback"),
        ]:
            response = getattr(client, method)(path)
            assert response.status_code == 503 and response.json()["code"] == "CHATGPT_UNAVAILABLE"
