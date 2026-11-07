import json
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import ToolReturnPart
from sqlalchemy import select

from gleanery.agent import build_agent, injection
from gleanery.agent.injection_reports import OPEN_REPORT_KEY
from gleanery.report import repo
from gleanery.store import open_database, repo_conversations
from gleanery.store.models import Report, ReportCitation
from gleanery.store.repo_settings import get_setting, set_setting
from tests.agent.test_data_tools import strip_untrusted
from tests.agent.test_plan_tools import FakeClock, call_model
from tests.support.agent import agent_deps
from tests.support.library import SENTINEL, seed_library


async def run_tool(
    deps: Any, name: str, args: dict[str, Any], history: Any = None
) -> tuple[Any, Any]:
    result = await build_agent().run(
        "继续", model=call_model(name, args), deps=deps, message_history=history
    )
    value = next(
        part.content
        for message in result.new_messages()
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    )
    return value, result.all_messages()


async def test_report_conversation(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    try:
        async with db.sessionmaker() as session:
            lib = await seed_library(session)
            await repo_conversations.create(session, 1)
            await session.commit()
        deps = agent_deps(db, tmp_path, collect=None, clock=FakeClock())
        text = f"结论很长。用户段落。[[c:{lib.contents['v1']}, m:{lib.comments['c1']}]]"
        saved, history = await run_tool(
            deps, "save_report", {"title": "报告", "markdown": text, "dataset_id": lib.dataset_a}
        )
        assert saved["version"] == 1 and saved["citations"] == 2
        report_id = saved["report_id"]
        async with db.sessionmaker() as session:
            assert len((await session.scalars(select(ReportCitation))).all()) == 2
            await repo.update(
                session,
                report_id,
                base_version=1,
                markdown=text.replace("用户段落", "用户手改段落"),
                source="user",
                conversation_id=1,
                now=2,
            )
            await session.commit()
        conflict, history = await run_tool(
            deps,
            "update_report",
            {
                "report_id": report_id,
                "base_version": 1,
                "edits": [{"old_text": "结论很长", "new_text": "结论短"}],
            },
            history,
        )
        assert conflict["error"]["code"] == "VERSION_CONFLICT"
        assert "用户手改段落" in conflict["current"]["markdown"]
        updated, history = await run_tool(
            deps,
            "update_report",
            {
                "report_id": report_id,
                "base_version": conflict["current"]["version"],
                "edits": [{"old_text": "结论很长", "new_text": "结论短"}],
            },
            history,
        )
        assert updated["version"] == 3
        detail, _ = await run_tool(deps, "get_report", {"report_id": report_id}, history)
        assert "结论短" in detail["markdown"] and "用户手改段落" in detail["markdown"]
        assert SENTINEL in json.dumps(detail, ensure_ascii=False)
        assert SENTINEL not in json.dumps(strip_untrusted(detail), ensure_ascii=False)
        page, _ = await run_tool(deps, "list_reports", {"limit": 1})
        assert page["total"] == 1 and page["items"][0]["this_conversation"]
    finally:
        await db.close()


async def test_unknown_citation_then_repair(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    try:
        async with db.sessionmaker() as session:
            lib = await seed_library(session)
            await repo_conversations.create(session, 1)
            await session.commit()
        deps = agent_deps(db, tmp_path, collect=None, clock=FakeClock())
        bad, history = await run_tool(
            deps, "save_report", {"title": "报告", "markdown": "[[c:99999, m:99999]]"}
        )
        assert bad["error"]["code"] == "UNKNOWN_CITATION"
        assert "c:99999" in bad["error"]["hint"] and "m:99999" in bad["error"]["hint"]
        async with db.sessionmaker() as session:
            assert (await session.scalars(select(Report))).all() == []
        good, _ = await run_tool(
            deps,
            "save_report",
            {"title": "报告", "markdown": f"[[c:{lib.contents['v1']}]]"},
            history,
        )
        assert good["version"] == 1
    finally:
        await db.close()


@pytest.mark.parametrize(
    "markdown", ["[[C:1]]", "[[" + ",".join(f"c:{i}" for i in range(11)) + "]]"]
)
async def test_invalid_citation(tmp_path: Path, markdown: str) -> None:
    db = await open_database(tmp_path)
    try:
        deps = agent_deps(db, tmp_path, collect=None, clock=FakeClock())
        value, _ = await run_tool(deps, "save_report", {"title": "报告", "markdown": markdown})
        assert value["error"]["code"] == "INVALID_CITATION"
    finally:
        await db.close()


@pytest.mark.parametrize(
    ("old", "code"), [("不存在", "EDIT_NOT_FOUND"), ("重复", "EDIT_AMBIGUOUS")]
)
async def test_edit_errors(tmp_path: Path, old: str, code: str) -> None:
    db = await open_database(tmp_path)
    try:
        async with db.sessionmaker() as session:
            await repo_conversations.create(session, 1)
            report = await repo.create(
                session,
                title="报告",
                markdown="重复 重复",
                dataset_id=None,
                conversation_id=1,
                source="agent",
                now=1,
            )
            report_id = report.id
            await session.commit()
        deps = agent_deps(db, tmp_path, collect=None, clock=FakeClock())
        value, _ = await run_tool(
            deps,
            "update_report",
            {
                "report_id": report_id,
                "base_version": 1,
                "edits": [{"old_text": old, "new_text": "新"}],
            },
        )
        assert value["error"]["code"] == code and "第 1 条" in value["error"]["hint"]
        async with db.sessionmaker() as session:
            report = await repo.get(session, report_id)
            assert report is not None and report.version == 1
    finally:
        await db.close()


async def test_report_injection(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    try:
        async with db.sessionmaker() as session:
            await repo_conversations.create(session, 1)
            report = await repo.create(
                session,
                title="报告",
                markdown="正文",
                dataset_id=None,
                conversation_id=1,
                source="agent",
                now=1,
            )
            report_id = report.id
            await set_setting(session, OPEN_REPORT_KEY.format(conversation_id=1), report_id)
            await session.commit()
            first = await injection.instructions(session, 1)
            assert first is not None and "工作区当前打开" in first
            await session.commit()
            again = await injection.instructions(session, 1)
            assert again is not None and "工作区当前打开" in again
            assert "用户在你上次之后改过" not in again
            await repo.update(
                session,
                report_id,
                base_version=1,
                markdown="用户修改",
                source="user",
                conversation_id=1,
                now=2,
            )
            await session.commit()
            changed = await injection.instructions(session, 1)
            assert (
                changed is not None
                and "用户在你上次之后改过" in changed
                and "get_report" in changed
            )
            await session.commit()
            quiet = await injection.instructions(session, 1)
            assert quiet is not None and "用户在你上次之后改过" not in quiet
            await repo.delete(session, report_id)
            await session.commit()
            assert await injection.instructions(session, 1) is None
            await session.commit()
            assert await get_setting(session, OPEN_REPORT_KEY.format(conversation_id=1)) is None
    finally:
        await db.close()


async def test_validation_order_and_revision_history(tmp_path: Path) -> None:
    db = await open_database(tmp_path)
    try:
        async with db.sessionmaker() as session:
            await repo_conversations.create(session, 1)
            report = await repo.create(
                session,
                title="报告",
                markdown="正文",
                dataset_id=None,
                conversation_id=1,
                source="agent",
                now=1,
            )
            report_id = report.id
            await session.commit()
            assert await injection.instructions(session, 1) is None
            await session.commit()
            await repo.update(
                session,
                report_id,
                base_version=1,
                markdown="用户修改",
                source="user",
                conversation_id=1,
                now=2,
            )
            await repo.update(
                session,
                report_id,
                base_version=2,
                title="Agent 修改",
                source="agent",
                conversation_id=1,
                now=3,
            )
            await session.commit()
            injected = await injection.instructions(session, 1)
            assert (
                injected is not None
                and "用户在你上次之后改过" in injected
                and "第 3 版" in injected
            )
        deps = agent_deps(db, tmp_path, collect=None, clock=FakeClock())
        value, _ = await run_tool(
            deps, "save_report", {"title": " ", "markdown": "[[C:1]]", "dataset_id": 99999}
        )
        assert value["error"]["code"] == "INVALID_REQUEST"
        value, _ = await run_tool(
            deps, "save_report", {"title": "标题", "markdown": "[[C:1]]", "dataset_id": 99999}
        )
        assert value["error"]["code"] == "DATASET_NOT_FOUND"
        value, _ = await run_tool(
            deps,
            "update_report",
            {
                "report_id": report_id,
                "base_version": 1,
                "edits": [{"old_text": "不存在", "new_text": "新"}],
            },
        )
        assert value["error"]["code"] == "VERSION_CONFLICT"
    finally:
        await db.close()
