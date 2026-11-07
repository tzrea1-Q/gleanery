from pathlib import Path

import httpx
import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from gleanery.app import create_app
from gleanery.collect.types import DEFAULT_RATE_LIMITS
from gleanery.deps import AppDeps, ResolvedModel
from gleanery.store import repo_conversations as repo
from gleanery.store.models import CollectionPlan, CollectionTask, Dataset
from tests.agent.test_plan_tools import FakeClock
from tests.support.memory import MemoryCredentialStore


@pytest.mark.parametrize(
    ("status", "intent", "model", "pending", "expected"),
    [
        ("completed", "整理报告", "ok", False, "started"),
        ("completed", None, "ok", False, "no_intent"),
        ("stopped", "整理报告", "ok", False, "incomplete"),
        ("completed", "整理报告", "none", False, "no_model"),
        ("completed", "整理报告", "ok", True, "approval_pending"),
        ("completed", "整理报告", "error", False, "started"),
    ],
)
async def test_finished(
    tmp_path: Path, status: str, intent: str | None, model: str, pending: bool, expected: str
) -> None:
    def respond(messages, info):
        if model == "error":
            raise ValueError("测试错误")
        return ModelResponse(parts=[TextPart("整理完成")])

    async def stream(messages, info):
        if model == "error":
            raise ValueError("测试错误")
        yield "整理完成"

    async def resolve(session):
        return (
            None
            if model == "none"
            else ResolvedModel(FunctionModel(respond, stream_function=stream), "测试")
        )

    app = create_app(
        AppDeps(tmp_path, "secret", 8765, FakeClock(), resolve, MemoryCredentialStore())
    )
    async with app.router.lifespan_context(app):
        async with app.state.db.sessionmaker() as session:
            conversation = await repo.create(session, 1)
            dataset = Dataset(name="测试集", description="", created_at=1)
            session.add(dataset)
            await session.flush()
            plan = CollectionPlan(
                conversation_id=conversation.id,
                status="confirmed",
                version=1,
                body={},
                target_dataset_id=dataset.id,
                created_at=1,
                updated_at=1,
            )
            session.add(plan)
            await session.flush()
            task = CollectionTask(
                plan_id=plan.id,
                dataset_id=dataset.id,
                conversation_id=conversation.id,
                platform="bili",
                status=status,
                queue_key=0,
                snapshot={
                    "plan_title": "测试计划",
                    "dataset_id": dataset.id,
                    "dataset_name": dataset.name,
                    "section": {},
                    "follow_up": intent,
                    "confirmed_at": 1,
                    "rate_limits": DEFAULT_RATE_LIMITS["bili"].model_dump(),
                },
                progress={"processed": 1, "planned": 2},
                created_at=1,
                updated_at=1,
            )
            session.add(task)
            await session.commit()
            cid, pid = conversation.id, plan.id
            if pending:
                await repo.append(
                    session,
                    conversation,
                    [
                        ModelRequest(parts=[UserPromptPart(content="开始")]),
                        ModelResponse(
                            parts=[
                                ToolCallPart(
                                    "start_collection", {"plan_id": pid}, tool_call_id="call-1"
                                )
                            ]
                        ),
                    ],
                    "测试",
                    1,
                )
        await app.state.follow_ups.finished(pid)
        async with app.state.db.sessionmaker() as session:
            rows = await repo.rows(session, cid)
            events = [
                row.payload["metadata"]["gleanery_event"] for row in rows if row.kind == "event"
            ]
            assert events[0]["auto_run"] == expected
            assert (events[-1]["type"] == "follow_up_failed") == (model == "error")
            if expected == "started" and model == "ok":
                assert "整理完成" in str(rows[-1].payload)
            if pending:
                assert rows[-2].kind == "event"
                assert rows[-1].kind == "response"
        if intent == "整理报告" and status == "completed" and model != "error":
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1:8765",
                cookies={"gleanery_session": "secret"},
                headers={"origin": "http://127.0.0.1:8765"},
            ) as client:
                async with app.state.runs.hold(cid, "follow_up"):
                    busy = await client.post(
                        f"/api/conversations/{cid}/follow-up", json={"plan_id": pid}
                    )
                    assert busy.status_code == 409 and busy.json()["code"] == "CONVERSATION_BUSY"
                    chat = await client.post(
                        "/api/chat",
                        json={
                            "id": str(cid),
                            "trigger": "submit-message",
                            "messages": [
                                {
                                    "id": "test",
                                    "role": "user",
                                    "parts": [{"type": "text", "text": "你好"}],
                                }
                            ],
                        },
                    )
                    assert chat.status_code == 409 and chat.json()["code"] == "CONVERSATION_BUSY"
                response = await client.post(
                    f"/api/conversations/{cid}/follow-up", json={"plan_id": pid}
                )
                if pending:
                    assert (
                        response.status_code == 409
                        and response.json()["code"] == "APPROVAL_PENDING"
                    )
                elif model == "none":
                    assert response.status_code == 409 and response.json()["code"] == "NO_MODEL"
                else:
                    assert response.status_code == 202
                    for background in list(app.state.follow_ups.tasks):
                        await background
        if status == "completed" and intent == "整理报告" and model == "ok" and not pending:
            async with app.state.db.sessionmaker() as session:
                task = await session.get(CollectionTask, task.id)
                assert task is not None
                task.status, task.reason, task.updated_at = "paused", "risk", 2
                await session.commit()
            await app.state.follow_ups.paused(task.id)
            await app.state.follow_ups.paused(task.id)
            async with app.state.db.sessionmaker() as session:
                rows = await repo.rows(session, cid)
                pauses = [
                    row
                    for row in rows
                    if row.kind == "event"
                    and row.payload["metadata"]["gleanery_event"]["type"] == "collection_paused"
                ]
                assert len(pauses) == 1


async def test_run_lock_waits_and_releases_on_cancel() -> None:
    import asyncio

    from gleanery.agent.runs import ConversationRuns
    from gleanery.events import EventBus

    runs = ConversationRuns(EventBus())
    entered = asyncio.Event()

    async def background() -> None:
        async with runs.hold(1, "follow_up"):
            entered.set()
            await asyncio.Event().wait()

    async with runs.hold(1, "chat"):
        task = asyncio.create_task(background())
        await asyncio.sleep(0)
        assert not entered.is_set()
        assert runs.busy(1) == "chat"
    await entered.wait()
    assert runs.busy(1) == "follow_up"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runs.busy(1) is None


async def test_event_before_pending_approval_keeps_approval_working(tmp_path: Path) -> None:
    """事件插在等审批的回复之前后，审批结果仍能接上那条回复。"""
    from pydantic_ai import DeferredToolResults, ToolDenied

    from gleanery.agent import build_agent
    from gleanery.agent.deps import agent_deps

    async def stream(messages, info):
        yield "好的，不开始"

    model = FunctionModel(stream_function=stream)

    async def resolve(session):
        return ResolvedModel(model, "测试")

    app = create_app(
        AppDeps(tmp_path, "secret", 8765, FakeClock(), resolve, MemoryCredentialStore())
    )
    async with app.router.lifespan_context(app):
        async with app.state.db.sessionmaker() as session:
            conversation = await repo.create(session, 1)
            await repo.append(
                session,
                conversation,
                [
                    ModelRequest(parts=[UserPromptPart(content="开始")]),
                    ModelResponse(
                        parts=[ToolCallPart("start_collection", {"plan_id": 1}, tool_call_id="c1")]
                    ),
                ],
                "测试",
                1,
            )
            await app.state.follow_ups.append_event(
                session,
                conversation,
                {"type": "collection_paused"},
                "系统事件（不是用户说的话）：暂停",
            )
            history = await repo.history(session, conversation.id)
            assert isinstance(history[-1], ModelResponse)
            assert history[-2].metadata == {"gleanery_event": {"type": "collection_paused"}}

        async def drain(ctx, events):
            async for _ in events:
                pass

        result = await build_agent().run(
            message_history=history,
            model=model,
            deps=agent_deps(app, conversation.id),
            deferred_tool_results=DeferredToolResults(approvals={"c1": ToolDenied("先不采")}),
            event_stream_handler=drain,
        )
        assert result.output == "好的，不开始"
