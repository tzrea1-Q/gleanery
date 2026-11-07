"""采集事件与后台 Agent 续跑。"""

import asyncio
import logging
from collections.abc import AsyncIterable
from typing import Any

from fastapi import FastAPI
from pydantic_ai import AgentStreamEvent, RunContext
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.agent import build_agent, injection
from gleanery.agent.deps import AgentDeps, agent_deps
from gleanery.collect.types import TaskProgress, TaskSnapshot
from gleanery.llm.errors import classify_model_error
from gleanery.store import repo_conversations as repo
from gleanery.store.models import CollectionPlan, CollectionTask, Conversation, Message
from gleanery.store.repo_settings import get_setting, set_setting

logger = logging.getLogger(__name__)


async def _drain(_: RunContext[AgentDeps], events: AsyncIterable[AgentStreamEvent]) -> None:
    async for _event in events:
        pass


def approval_pending(history: list) -> bool:
    return bool(
        history
        and isinstance(history[-1], ModelResponse)
        and any(isinstance(part, ToolCallPart) for part in history[-1].parts)
    )


class FollowUps:
    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.collect = app.state.collect
        self.tasks: set[asyncio.Task] = set()
        self.pauses: set[tuple[int, int]] = set()
        self.pending: set[int] = set()
        self.listener: asyncio.Task | None = None

    def start(self) -> None:
        self.collect.plan_finished_hooks.append(self.plan_finished)
        self.listener = asyncio.create_task(self.listen())

    def spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def close(self) -> None:
        self.collect.plan_finished_hooks.remove(self.plan_finished)
        tasks = list(self.tasks)
        if self.listener:
            tasks.append(self.listener)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def plan_finished(self, plan_id: int) -> None:
        self.spawn(self.finished(plan_id))

    async def listen(self) -> None:
        async for event in self.app.state.events.subscribe():
            if event.type == "task.updated":
                self.spawn(self.paused(event.data["task_id"]))

    async def append_event(
        self, session: AsyncSession, conversation: Conversation, data: dict[str, Any], text: str
    ) -> None:
        rows = await repo.rows(session, conversation.id)
        history = ModelMessagesTypeAdapter.validate_python([row.payload for row in rows])
        seq = rows[-1].seq + 1 if rows else 0
        if approval_pending(history):
            rows[-1].seq += 1
            seq -= 1
            await session.flush()
        message = ModelRequest(
            parts=[UserPromptPart(content=text)], metadata={"gleanery_event": data}
        )
        payload = ModelMessagesTypeAdapter.dump_python([message], mode="json")[0]
        now = self.app.state.deps.clock.now_ms()
        session.add(
            Message(
                conversation_id=conversation.id,
                seq=seq,
                kind="event",
                payload=payload,
                model_name=None,
                created_at=now,
            )
        )
        conversation.updated_at = now
        await session.commit()
        self.app.state.events.publish("conversation.updated", {"conversation_id": conversation.id})

    async def paused(self, task_id: int) -> None:
        async with self.app.state.db.sessionmaker() as session:
            task = await session.get(CollectionTask, task_id)
            if (
                not task
                or task.status != "paused"
                or task.reason not in ("risk", "login_lost")
                or task.conversation_id is None
                or task.plan_id is None
            ):
                return
            key = (task.id, task.updated_at)
            if key in self.pauses:
                return
            self.pauses.add(key)
            conversation_id = task.conversation_id
            signature = injection._signature(task)
            snapshot = TaskSnapshot.model_validate(task.snapshot)
            line = injection._line(task)
            data = {
                "type": "collection_paused",
                "plan_id": task.plan_id,
                "task_id": task.id,
                "platform": task.platform,
                "reason": task.reason,
            }
        async with (
            self.app.state.runs.hold(conversation_id, None),
            self.app.state.db.sessionmaker() as session,
        ):
            conversation = await session.get(Conversation, conversation_id)
            if conversation:
                seen = await get_setting(session, injection._key(conversation_id), {}) or {}
                seen[str(task_id)] = signature
                await set_setting(session, injection._key(conversation_id), seen)
                await self.append_event(
                    session,
                    conversation,
                    data,
                    f"系统事件（不是用户说的话）：计划「{snapshot.plan_title}」采集暂停。\n{line}\n数据集：{snapshot.dataset_name}（ID {snapshot.dataset_id}）；后续意图：{(snapshot.follow_up or '无').rstrip('。')}。没有自动续跑，等用户决定。",
                )

    async def finished(self, plan_id: int) -> None:
        async with self.app.state.db.sessionmaker() as session:
            plan = await session.get(CollectionPlan, plan_id)
            if not plan or plan.conversation_id is None:
                return
            conversation_id = plan.conversation_id
        async with (
            self.app.state.runs.hold(conversation_id, None),
            self.app.state.db.sessionmaker() as session,
        ):
            plan = await session.get(CollectionPlan, plan_id)
            conversation = await session.get(Conversation, conversation_id)
            tasks = list(
                await session.scalars(
                    select(CollectionTask)
                    .where(CollectionTask.plan_id == plan_id)
                    .order_by(CollectionTask.id)
                )
            )
            if not plan or not conversation or not tasks:
                return
            snapshot = TaskSnapshot.model_validate(tasks[0].snapshot)
            history = await repo.history(session, conversation_id)
            resolved = await self.app.state.deps.model_resolver(session)
            outcome = (
                "completed" if all(task.status == "completed" for task in tasks) else "incomplete"
            )
            auto = (
                "incomplete"
                if outcome == "incomplete"
                else "no_intent"
                if not snapshot.follow_up
                else "approval_pending"
                if approval_pending(history)
                else "no_model"
                if resolved is None
                else "started"
            )
            entries = [
                {
                    "task_id": task.id,
                    "platform": task.platform,
                    "status": task.status,
                    "processed": TaskProgress.model_validate(task.progress).processed,
                    "planned": TaskProgress.model_validate(task.progress).planned,
                }
                for task in tasks
            ]
            data = {
                "type": "collection_finished",
                "plan_id": plan_id,
                "plan_title": snapshot.plan_title,
                "dataset_id": snapshot.dataset_id,
                "outcome": outcome,
                "tasks": entries,
                "follow_up": snapshot.follow_up,
                "auto_run": auto,
            }
            lines = [
                f"系统事件（不是用户说的话）：计划「{snapshot.plan_title}」采集结束。",
                *(injection._line(task) for task in tasks),
                f"数据集：{snapshot.dataset_name}（ID {snapshot.dataset_id}）；后续意图：{(snapshot.follow_up or '无').rstrip('。')}。",
                "请按后续意图继续整理，完成后简短告诉用户结果。"
                if auto == "started"
                else f"没有自动续跑：{auto}，等用户决定。",
            ]
            seen = await get_setting(session, injection._key(conversation_id), {}) or {}
            seen.update({str(task.id): injection._signature(task) for task in tasks})
            await set_setting(session, injection._key(conversation_id), seen)
            await self.append_event(session, conversation, data, "\n".join(lines))
            if auto == "started" and resolved is not None:
                async with self.app.state.runs.announce(conversation_id, "follow_up"):
                    await self.run(session, conversation, plan_id, resolved)

    async def run(
        self,
        session: AsyncSession,
        conversation: Conversation,
        plan_id: int,
        resolved,
        *,
        manual: bool = False,
    ) -> None:
        from gleanery.api.chat import _on_model_failure

        try:
            history = await repo.history(session, conversation.id)
            injected = await injection.instructions(session, conversation.id)
            if manual:
                injected = "\n".join(
                    filter(
                        None,
                        [
                            injected,
                            "用户要求用已有数据继续整理，请根据采集事件中的后续意图处理并简短告知结果。 ",
                        ],
                    )
                )
            await session.commit()
            # 给了事件流处理器，模型就按流式调用，与对话路由一致（有的提供商只稳定支持流式）。
            result = await build_agent().run(
                message_history=history,
                model=resolved.model,
                deps=agent_deps(self.app, conversation.id),
                instructions=injected,
                event_stream_handler=_drain,
            )
            messages = [
                message
                for message in result.new_messages()
                if message.kind == "response"
                or not any(isinstance(part, UserPromptPart) for part in message.parts)
            ]
            if messages:
                await repo.append(
                    session,
                    conversation,
                    messages,
                    resolved.model_name,
                    self.app.state.deps.clock.now_ms(),
                )
                self.app.state.events.publish(
                    "conversation.updated", {"conversation_id": conversation.id}
                )
        except Exception as exc:
            await session.rollback()
            failure = classify_model_error(exc, resolved.kind)
            await _on_model_failure(session, resolved, self.app.state.events, failure)
            message = failure.body.message
            await self.append_event(
                session,
                conversation,
                {
                    "type": "follow_up_failed",
                    "plan_id": plan_id,
                    "code": failure.body.code,
                    "message": message,
                },
                f"系统事件（不是用户说的话）：{message}。没有自动续跑，等用户决定。",
            )

    async def retry(self, conversation_id: int, plan_id: int) -> None:
        try:
            async with (
                self.app.state.runs.hold(conversation_id, "follow_up"),
                self.app.state.db.sessionmaker() as session,
            ):
                conversation = await session.get(Conversation, conversation_id)
                resolved = await self.app.state.deps.model_resolver(session)
                if conversation and resolved:
                    await self.run(session, conversation, plan_id, resolved, manual=True)
        finally:
            self.pending.discard(conversation_id)
