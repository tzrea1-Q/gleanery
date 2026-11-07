from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

import gleanery.app
from gleanery.agent import build_agent
from gleanery.collect.plan import PlanBody
from gleanery.collect.plan_check import check
from gleanery.collect.service import CollectService, PlatformView
from gleanery.deps import AppDeps, ResolvedModel
from gleanery.platforms.types import ContentRecord
from gleanery.store import open_database, repo_content, repo_conversations, repo_plans
from tests.support.agent import agent_deps
from tests.support.memory import MemoryCredentialStore


class FakeClock:
    def now_ms(self) -> int:
        return 1234

    async def sleep(self, seconds: float) -> None:
        raise AssertionError("不应等待")


class FakeCollect(CollectService):
    def __init__(self) -> None:
        self.runtime = cast(Any, SimpleNamespace(platforms=frozenset({"bili"})))
        self.enqueued: list[int] = []
        self.awakened: list[str] = []

    # 假执行器不起 worker；app 的 lifespan 会调用这两个方法。
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def quota_remaining(self, session, platform):
        return 1000

    async def platform_view(self, session, platform):
        return PlatformView(
            platform=platform,
            state="normal",
            reason=None,
            wait_reason=None,
            wait_until=None,
            cooldown_until=None,
            locked_until=None,
            quota_used=0,
            daily_quota=1000,
            warmup_until=None,
            last_probe_at=None,
            last_probe_ok=None,
            last_probe_detail=None,
            queue_length=0,
        )

    async def enqueue_plan(self, session, plan, dataset, sections, resolved, now):
        self.enqueued.append(plan.id)
        return []

    async def task_views(self, session, **kwargs):
        return []

    def wake(self, platform):
        self.awakened.append(platform)


def body(quantity: int = 1) -> PlanBody:
    return PlanBody.model_validate(
        {
            "title": "测试",
            "sections": [
                {"platform": "bili", "keywords": ["关键词"], "quantity": quantity, "depth": {}}
            ],
        }
    )


def call_model(name: str, args: dict[str, Any]) -> FunctionModel:
    def respond(messages, info):
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("完成")])
        return ModelResponse(parts=[ToolCallPart(name, args, tool_call_id="call-1")])

    return FunctionModel(respond)


@pytest.mark.parametrize("approved", [True, False])
async def test_approval_roundtrip(tmp_path: Path, approved: bool) -> None:
    db = await open_database(tmp_path)
    collect = FakeCollect()
    deps = agent_deps(db, tmp_path, collect=collect, clock=FakeClock())
    async with db.sessionmaker() as session:
        await repo_conversations.create(session, 1)
        plan = await repo_plans.create_draft(session, None, body(), 1)
        plan_id = plan.id
        await session.commit()
    agent = build_agent()
    result = await agent.run(
        "启动", model=call_model("start_collection", {"plan_id": plan_id}), deps=deps
    )
    assert isinstance(result.output, DeferredToolRequests)
    assert result.output.approvals[0].tool_call_id == "call-1"
    resumed = await agent.run(
        message_history=result.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals={"call-1": approved}),
        model=call_model("start_collection", {"plan_id": plan_id}),
        deps=deps,
    )
    assert resumed.output == "完成"
    async with db.sessionmaker() as session:
        saved = await repo_plans.get(session, plan_id)
        assert saved is not None
        assert saved.status == ("confirmed" if approved else "draft")
    assert collect.enqueued == ([plan_id] if approved else [])
    assert collect.awakened == (["bili"] if approved else [])
    await db.close()


async def test_invalid_and_locked_do_not_request_approval(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    deps = agent_deps(db, tmp_path, collect=FakeCollect(), clock=FakeClock())
    async with db.sessionmaker() as session:
        invalid = await repo_plans.create_draft(session, None, body(301), 1)
        locked = await repo_plans.create_draft(session, None, body(), 1)
        locked.status = "confirmed"
        ids = [invalid.id, locked.id]
        await session.commit()
    for plan_id, code in zip(ids, ["HARD_CAP_EXCEEDED", "PLAN_LOCKED"], strict=True):
        result = await build_agent().run(
            "启动", model=call_model("start_collection", {"plan_id": plan_id}), deps=deps
        )
        returns = [
            part
            for message in result.all_messages()
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        assert cast(Any, returns[0].content)["error"]["code"] == code
    await db.close()


async def test_update_conflict_and_lock(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    deps = agent_deps(db, tmp_path, collect=FakeCollect(), clock=FakeClock())
    async with db.sessionmaker() as session:
        plan = await repo_plans.create_draft(session, None, body(), 1)
        plan_id = plan.id
        await repo_plans.replace(session, plan_id, 1, body(2), 2)
        await session.commit()
    args = {"plan_id": plan_id, "base_version": 1, "plan": body().model_dump(mode="json")}
    for code in ("VERSION_CONFLICT", "PLAN_LOCKED"):
        result = await build_agent().run(
            "修改", model=call_model("update_collection_plan", args), deps=deps
        )
        returns = [
            part
            for message in result.all_messages()
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]
        response = cast(Any, returns[0].content)["error"]
        assert response["code"] == code
        if code == "VERSION_CONFLICT":
            assert '"version": 2' in response["hint"] and '"quantity": 2' in response["hint"]
            async with db.sessionmaker() as session:
                plan = await repo_plans.get(session, plan_id)
                assert plan is not None
                plan.status = "confirmed"
                await session.commit()
    await db.close()


async def test_approval_rechecks_latest_draft(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    collect = FakeCollect()
    deps = agent_deps(db, tmp_path, collect=collect, clock=FakeClock())
    async with db.sessionmaker() as session:
        plan = await repo_plans.create_draft(session, None, body(), 1)
        plan_id = plan.id
        await session.commit()
    model = call_model("start_collection", {"plan_id": plan_id})
    agent = build_agent()
    pending = await agent.run("启动", model=model, deps=deps)
    assert isinstance(pending.output, DeferredToolRequests)
    async with db.sessionmaker() as session:
        await repo_plans.replace(session, plan_id, 1, body(301), 2)
        await session.commit()
    resumed = await agent.run(
        message_history=pending.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals={"call-1": True}),
        model=model,
        deps=deps,
    )
    returns = [
        part
        for message in resumed.new_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    assert cast(Any, returns[0].content)["error"]["code"] == "HARD_CAP_EXCEEDED"
    assert collect.enqueued == []
    await db.close()


async def test_plan_checks_targets_and_platforms(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    async with db.sessionmaker() as session:
        record = ContentRecord(
            platform="bili",
            platform_id="BV1234567890",
            url="https://www.bilibili.com/video/BV1234567890",
            kind="video",
            completeness="summary",
        )
        ids = await repo_content.upsert_contents(session, [record], None, 1)
        plan = PlanBody.model_validate(
            {
                "title": "校验",
                "sections": [
                    {
                        "platform": "bili",
                        "depth": {},
                        "quantity": 0,
                        "targets": [
                            f"content:{ids['BV1234567890']}",
                            "https://b23.tv/short",
                            "content:999",
                        ],
                    },
                    {"platform": "bili", "depth": {}, "quantity": 0},
                    {
                        "platform": "xhs",
                        "depth": {},
                        "quantity": 0,
                        "targets": [f"content:{ids['BV1234567890']}"],
                    },
                ],
            }
        )
        issues, resolved = await check(session, plan, FakeCollect(), 1)
        codes = [issue.code for issue in issues]
        assert codes.count("UNRESOLVABLE_LINK") == 3
        assert {"DUPLICATE_PLATFORM", "EMPTY_SECTION", "PLATFORM_UNSUPPORTED"} <= set(codes)
        assert resolved["bili"][0].platform_id == "BV1234567890"
    await db.close()


@pytest.mark.parametrize("approved", [True, False])
def test_chat_approval(tmp_path: Path, approved: bool) -> None:
    seen: list[str] = []

    async def stream(messages, info):
        seen.append(str(messages))
        if any(isinstance(part, ToolReturnPart) for part in messages[-1].parts):
            yield "完成"
        else:
            yield {
                0: DeltaToolCall(
                    name="start_collection", json_args='{"plan_id":1}', tool_call_id="call-1"
                )
            }

    model = FunctionModel(stream_function=stream)

    async def resolve(session):
        return ResolvedModel(model, "测试")

    deps = AppDeps(tmp_path, "secret", 8765, FakeClock(), resolve, MemoryCredentialStore())
    with TestClient(gleanery.app.create_app(deps), base_url="http://127.0.0.1:8765") as client:
        client.cookies.set("gleanery_session", "secret")
        client.headers["origin"] = "http://127.0.0.1:8765"
        collect = FakeCollect()
        app = cast(FastAPI, client.app)
        app.state.collect = collect
        conversation_id = client.post("/api/conversations").json()["id"]

        async def create_plan():
            async with app.state.db.sessionmaker() as session:
                plan = await repo_plans.create_draft(session, conversation_id, body(), 1)
                await session.commit()
                return plan.id

        assert client.portal is not None
        assert client.portal.call(create_plan) == 1
        request = {
            "id": str(conversation_id),
            "trigger": "submit-message",
            "messages": [
                {"id": "user-1", "role": "user", "parts": [{"type": "text", "text": "启动"}]}
            ],
        }
        response = client.post("/api/chat", json=request)
        assert "tool-approval-request" in response.text, response.text
        assistant = {
            "id": "assistant-1",
            "role": "assistant",
            "parts": [
                {
                    "type": "tool-start_collection",
                    "toolCallId": "call-1",
                    "state": "approval-responded",
                    "input": {"plan_id": 1},
                    "approval": {"id": "call-1", "approved": approved, "reason": "不需要"},
                }
            ],
        }
        request["messages"].append(assistant)
        response = client.post("/api/chat", json=request)
        assert response.status_code == 200 and "完成" in response.text, response.text
        assert collect.enqueued == ([1] if approved else [])
        assert ("不需要" in seen[-1]) is (not approved)

        async def saved_history():
            async with app.state.db.sessionmaker() as session:
                return str(await repo_conversations.history(session, conversation_id))

        assert ("不需要" in client.portal.call(saved_history)) is (not approved)
