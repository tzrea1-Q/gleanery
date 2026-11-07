import asyncio
import json
import time
from dataclasses import asdict, replace
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2
import pydantic_ai.providers.openai_chatgpt as oauth
import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters, override_allow_model_requests
from sqlalchemy import select

from gleanery.llm.chatgpt import PENDING_TTL_MS, ChatGPTPlan
from gleanery.llm.credentials import FileCredentialStore
from gleanery.llm.errors import classify_model_error
from gleanery.store import open_database
from gleanery.store.models import ModelConfig
from tests.support.fake_siwc import FakeSIWC, jwt


class Clock:
    def __init__(self) -> None:
        self.value = 1000

    def now_ms(self) -> int:
        return self.value

    async def sleep(self, seconds: float) -> None:
        raise AssertionError("不应等待")


@pytest.fixture
async def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake = FakeSIWC()
    transport = httpx2.ASGITransport(app=fake.app)
    original = vars(oauth)["_post_token_request"]

    async def exchange(*args, **kwargs):
        if kwargs.get("http_client") is not None:
            return await original(*args, **kwargs)
        async with httpx2.AsyncClient(transport=transport) as client:
            return await original(*args, **kwargs, http_client=client)

    monkeypatch.setattr(oauth, "_post_token_request", exchange)
    db = await open_database(tmp_path)
    clock = Clock()
    store = FileCredentialStore(tmp_path)
    plan = ChatGPTPlan(store, clock, 8765, transport)
    async with db.sessionmaker() as session:
        yield fake, plan, session, clock, store
    await plan.close()
    await db.close()


async def login(fake, plan, session):
    query = parse_qs(urlsplit(await plan.start(session)).query)
    fake.challenge, fake.nonce = query["code_challenge"][0], query["nonce"][0]
    result = await plan.complete(
        session, {"state": query["state"][0], "code": "code", "client_id": "oaiapp_test"}
    )
    assert result.changed
    config = await session.scalar(select(ModelConfig).where(ModelConfig.kind == "chatgpt_plan"))
    assert config is not None
    return query, config


async def test_状态一次性且过期边界正确(setup) -> None:
    _, plan, session, clock, _ = setup
    query = parse_qs(urlsplit(await plan.start(session)).query)
    assert (await plan.complete(session, {})).status == 400
    assert (await plan.complete(session, {"state": "wrong"})).status == 400
    clock.value += PENDING_TTL_MS
    assert (
        await plan.complete(session, {"state": query["state"][0], "error": "denied"})
    ).status == 200
    assert (await plan.complete(session, {"state": query["state"][0]})).status == 400
    query = parse_qs(urlsplit(await plan.start(session)).query)
    clock.value += PENDING_TTL_MS + 1
    assert (await plan.complete(session, {"state": query["state"][0]})).status == 400


async def test_错误的状态不影响挂起的登录(setup) -> None:
    fake, plan, session, _, _ = setup
    query = parse_qs(urlsplit(await plan.start(session)).query)
    assert (await plan.complete(session, {"state": "wrong", "code": "code"})).status == 400
    fake.challenge, fake.nonce = query["code_challenge"][0], query["nonce"][0]
    result = await plan.complete(
        session, {"state": query["state"][0], "code": "code", "client_id": "oaiapp_test"}
    )
    assert result.message == "已连接，可以关闭此页面。" and result.changed


async def test_回调里的账号和提示不同时不保存(setup) -> None:
    fake, plan, session, _, _ = setup
    _, config = await login(fake, plan, session)
    await plan.disconnect(config)
    again = parse_qs(urlsplit(await plan.start(session)).query)
    fake.challenge, fake.nonce = again["code_challenge"][0], again["nonce"][0]
    fake.subject = "other"
    result = await plan.complete(session, {"state": again["state"][0], "code": "code"})
    assert result.message == "要换账号，先在设置里删除这份配置。"
    assert not plan.has_refresh_token(config.id) and config.status == "needs_reconnect"


async def test_断开后刷新模型列表保持原状(setup) -> None:
    fake, plan, session, clock, _ = setup
    _, config = await login(fake, plan, session)
    await plan.disconnect(config)
    await plan.refresh_models(config, clock.now_ms())
    assert (config.status, config.status_reason) == ("needs_reconnect", "已断开")
    assert config.available_models == ["fake-model"]


async def test_多轮共用一个provider_中途刷新后继续(setup) -> None:
    fake, plan, session, _, store = setup
    fake.failed_stream = False
    _, config = await login(fake, plan, session)
    with override_allow_model_requests(True):
        agent = Agent()
        first = await agent.run("你好", model=plan.make_model(config, "fake-model"))
        assert first.output == "你好"
        provider = plan._provider(config)[0]
        stale = replace(provider.credentials, access_token=jwt({"exp": 1}))
        store.set(config.id, json.dumps(asdict(stale)))
        provider._replace(stale)
        second = await agent.run("再来", model=plan.make_model(config, "fake-model"))
    assert second.output == "你好" and fake.refresh_count == 1
    assert json.loads(store.get(config.id))["refresh_token"] == "refresh-1"
    assert fake.requests[-1][1] != f"Bearer {stale.access_token}"


async def test_429不重试(setup) -> None:
    fake, plan, session, _, _ = setup
    _, config = await login(fake, plan, session)
    fake.responses_status = 429
    with override_allow_model_requests(True), pytest.raises(ModelHTTPError) as caught:
        await Agent().run("你好", model=plan.make_model(config, "fake-model"))
    assert caught.value.status_code == 429 and len(fake.requests) == 1


async def test_动态注册断开重连与撤销失败(setup) -> None:
    fake, plan, session, _, _ = setup
    query, config = await login(fake, plan, session)
    assert query["client_id"] == ["dynamic_agent_client"]
    assert query["agent_name_hint"] == ["Gleanery"]
    assert query["code_challenge_method"] == ["S256"]
    assert fake.token_clients == ["oaiapp_test"]
    assert config.available_models == ["fake-model"] and config.model_labels == {
        "fake-model": "假模型"
    }
    fake.revoke_status = 500
    await plan.disconnect(config)
    assert fake.revocations == 1 and not plan.has_refresh_token(config.id)
    assert config.status == "needs_reconnect" and config.client_id == "oaiapp_test"
    again = parse_qs(urlsplit(await plan.start(session)).query)
    assert again["client_id"] == ["oaiapp_test"] and "id_token_hint" in again
    assert (
        "agent_name_hint" not in again and again["ext_agent_host_id"] == query["ext_agent_host_id"]
    )
    fake.revoke_status = 200
    fake.challenge, fake.nonce = again["code_challenge"][0], again["nonce"][0]
    result = await plan.complete(session, {"state": again["state"][0], "code": "code"})
    assert result.status == 200 and plan.has_refresh_token(config.id)
    await plan.forget(config)
    assert fake.revocations == 2 and not plan.has_refresh_token(config.id)


async def test_未授权套餐再次提示同意(setup) -> None:
    fake, plan, session, _, _ = setup
    fake.scope = "openid offline_access"
    _, config = await login(fake, plan, session)
    assert (config.status, config.status_reason) == ("needs_reconnect", "未授权使用 ChatGPT 套餐")
    assert config.available_models is None
    assert parse_qs(urlsplit(await plan.start(session)).query)["prompt"] == ["consent"]


async def test_并发刷新只执行一次且写回(setup) -> None:
    fake, plan, session, _, store = setup
    _, config = await login(fake, plan, session)
    await plan._drop(config.id)
    saved = json.loads(store.get(config.id))
    saved["access_token"] = jwt({"exp": int(time.time()) - 10})
    store.set(config.id, json.dumps(saved))
    model = plan.make_model(config, "fake-model")

    async def run_round() -> None:
        with pytest.raises(ModelAPIError):
            async with model.request_stream(
                [ModelRequest(parts=[UserPromptPart(content="你好")])],
                None,
                ModelRequestParameters(),
            ) as stream:
                async for _ in stream:
                    pass

    with override_allow_model_requests(True):
        await asyncio.gather(run_round(), run_round())
    assert fake.refresh_count == 1
    assert json.loads(store.get(config.id))["refresh_token"] == "refresh-1"
    assert plan.make_model(config, "fake-model").client is plan._provider(config)[0].client


async def test_刷新被拒时配置需要重连(setup) -> None:
    fake, plan, session, clock, store = setup
    _, config = await login(fake, plan, session)
    await plan._drop(config.id)
    saved = json.loads(store.get(config.id))
    saved["access_token"] = jwt({"exp": int(time.time()) - 10})
    store.set(config.id, json.dumps(saved))
    fake.reject_refresh = True
    model = plan.make_model(config, "fake-model")
    with override_allow_model_requests(True), pytest.raises(ModelAPIError) as caught:
        async with model.request_stream(
            [ModelRequest(parts=[UserPromptPart(content="你好")])], None, ModelRequestParameters()
        ) as stream:
            async for _ in stream:
                pass
    assert (
        classify_model_error(caught.value, "chatgpt_plan").body.code == "MODEL_RECONNECT_REQUIRED"
    )
    await plan.refresh_models(config, clock.now_ms())
    assert config.status == "needs_reconnect"


async def test_流错误与请求形态(setup) -> None:
    fake, plan, session, _, _ = setup
    _, config = await login(fake, plan, session)
    model = plan.make_model(config, "fake-model")
    with override_allow_model_requests(True), pytest.raises(ModelAPIError) as caught:
        async with model.request_stream(
            [ModelRequest(parts=[UserPromptPart(content="你好")])], None, ModelRequestParameters()
        ) as stream:
            async for _ in stream:
                pass
    assert classify_model_error(caught.value, "chatgpt_plan").body.code == "MODEL_QUOTA_EXCEEDED"
    body, authorization = fake.requests[-1]
    assert body["store"] is False and body["stream"] is True
    assert authorization.startswith("Bearer ")
    assert "temperature" not in body and "max_output_tokens" not in body
