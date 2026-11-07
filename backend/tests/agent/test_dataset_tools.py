from pathlib import Path

import pytest
from pydantic_ai import DeferredToolRequests, DeferredToolResults, ToolDenied
from pydantic_ai.messages import ToolReturnPart
from sqlalchemy import select

from gleanery.agent import build_agent
from gleanery.store import repo_conversations
from gleanery.store.db import open_database
from gleanery.store.models import Dataset, DatasetItem
from tests.agent.test_plan_tools import FakeClock, FakeCollect, call_model
from tests.support.agent import agent_deps
from tests.support.library import seed_library


@pytest.mark.parametrize("tool", ["remove_from_dataset", "delete_dataset"])
@pytest.mark.parametrize("approved", [True, False])
async def test_approval(tmp_path: Path, tool: str, approved: bool) -> None:
    db = await open_database(tmp_path)
    try:
        async with db.sessionmaker() as session:
            lib = await seed_library(session)
        deps = agent_deps(db, tmp_path, collect=FakeCollect(), clock=FakeClock())
        args = {"dataset_id": lib.dataset_a}
        if tool == "remove_from_dataset":
            args["content_ids"] = [lib.contents["v1"]]  # type: ignore[assignment]
        model = call_model(tool, args)
        agent = build_agent()
        result = await agent.run("操作", model=model, deps=deps)
        assert isinstance(result.output, DeferredToolRequests)
        async with db.sessionmaker() as session:
            assert await session.get(Dataset, lib.dataset_a) is not None
            assert await session.get(DatasetItem, (lib.dataset_a, lib.contents["v1"])) is not None
        decision = True if approved else ToolDenied(message="暂时不要")
        resumed = await agent.run(
            message_history=result.all_messages(),
            deferred_tool_results=DeferredToolResults(approvals={"call-1": decision}),
            model=model,
            deps=deps,
        )
        if not approved:
            assert any(
                "暂时不要" in str(part.content)
                for message in resumed.all_messages()
                for part in message.parts
                if isinstance(part, ToolReturnPart)
            )
        async with db.sessionmaker() as session:
            assert (await session.get(Dataset, lib.dataset_a) is None) == (
                approved and tool == "delete_dataset"
            )
            members = (
                await session.scalars(
                    select(DatasetItem.content_id).where(DatasetItem.dataset_id == lib.dataset_a)
                )
            ).all()
            assert (lib.contents["v1"] not in members) == approved
    finally:
        await db.close()


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"name": " ", "description": "", "content_ids": [1]}, "名称不能为空"),
        (
            {"name": "前三", "description": "", "content_ids": [1], "source_dataset_id": 1},
            "content_ids 和 source_dataset_id 只能给一个",
        ),
        ({"name": "前三", "description": ""}, "要给 content_ids 或 source_dataset_id"),
    ],
)
async def test_save_as_dataset_explains_invalid_args(
    tmp_path: Path, args: dict[str, object], message: str
) -> None:
    """2026-11-02 M2 冒烟：模型同时给了两种来源，旧报错没说清错在哪。"""
    db = await open_database(tmp_path)
    try:
        deps = agent_deps(db, tmp_path, collect=FakeCollect(), clock=FakeClock())
        result = await build_agent().run(
            "另存", model=call_model("save_as_dataset", args), deps=deps
        )
        returned = next(
            part.content
            for message_ in result.all_messages()
            for part in message_.parts
            if isinstance(part, ToolReturnPart)
        )
        assert f"'message': '{message}'" in str(returned)
    finally:
        await db.close()


async def test_save_as_dataset_from_ids(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    try:
        async with db.sessionmaker() as session:
            lib = await seed_library(session)
            await repo_conversations.create(session, 1)
            await session.commit()
        deps = agent_deps(db, tmp_path, collect=FakeCollect(), clock=FakeClock())
        ids = [lib.contents["v1"], lib.contents["v3"]]
        await build_agent().run(
            "另存",
            model=call_model(
                "save_as_dataset", {"name": "精选", "description": "两条", "content_ids": ids}
            ),
            deps=deps,
        )
        async with db.sessionmaker() as session:
            dataset = await session.scalar(select(Dataset).where(Dataset.name == "精选"))
            assert dataset is not None
            members = (
                await session.scalars(
                    select(DatasetItem.content_id).where(DatasetItem.dataset_id == dataset.id)
                )
            ).all()
            assert sorted(members) == sorted(ids)
    finally:
        await db.close()
