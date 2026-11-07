"""每轮 Agent 运行前的系统注入。

`instructions` 拼接两部分：上一轮以来本对话相关任务的状态变化（M1），以及当前打开的报告与
用户改过的报告（M3，见 `injection_reports`）。
上一轮看到的任务状态存在 setting 表，每次注入后更新，所以同一个变化只告诉 Agent 一次。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.collect.types import TaskProgress, TaskSnapshot
from gleanery.store.models import CollectionTask
from gleanery.store.repo_settings import get_setting, set_setting

PLATFORM_NAMES = {"bili": "B 站", "xhs": "小红书"}
STATUS_TEXT = {
    "queued": "排队中",
    "running": "执行中",
    "paused": "已暂停",
    "completed": "已完成",
    "stopped": "已停止",
    "failed": "失败",
}
REASON_TEXT = {
    "risk": "触发风控，等用户选择继续或停止",
    "login_lost": "登录失效，等用户扫码",
    "user": "用户暂停",
    "browser_disconnected": "浏览器断开",
    "app_restart": "应用重启后中断，等用户点继续",
    "page_changed": "页面改版",
    "network": "网络错误重试后仍失败",
}


def _key(conversation_id: int) -> str:
    return f"agent.injected_tasks.{conversation_id}"


def _signature(task: CollectionTask) -> str:
    progress = TaskProgress.model_validate(task.progress)
    return f"{task.status}|{task.reason or ''}|{progress.processed}"


def _line(task: CollectionTask) -> str:
    progress = TaskProgress.model_validate(task.progress)
    title = TaskSnapshot.model_validate(task.snapshot).plan_title
    platform = PLATFORM_NAMES.get(task.platform, task.platform)
    text = f"- 计划「{title}」的{platform}任务（task_id={task.id}）：{STATUS_TEXT.get(task.status, task.status)}"
    if task.reason:
        text += f"，{REASON_TEXT.get(task.reason, task.reason)}"
    text += f"；实得 {progress.processed} / 计划 {progress.planned}，评论 {progress.comments} 条"
    # 小红书没有字幕，写上"字幕 0 份"模型会当成没采到。
    if task.platform == "bili":
        text += f"（含楼中楼），字幕 {progress.subtitles} 份"
    else:
        text += "（含二级评论）"
    return text


async def task_changes(session: AsyncSession, conversation_id: int) -> str | None:
    """返回要注入的说明，没有变化时返回 None。会更新已注入的快照，由调用方提交。"""
    tasks = list(
        await session.scalars(
            select(CollectionTask)
            .where(CollectionTask.conversation_id == conversation_id)
            .order_by(CollectionTask.id)
        )
    )
    seen: dict[str, Any] = await get_setting(session, _key(conversation_id), {}) or {}
    current = {str(task.id): _signature(task) for task in tasks}
    changed = [task for task in tasks if seen.get(str(task.id)) != current[str(task.id)]]
    if current != seen:
        await set_setting(session, _key(conversation_id), current)
    if not changed:
        return None
    # 计划标题来自 Agent 与用户，不含平台内容，不必放进 untrusted。
    return "\n".join(
        [
            "系统注入（不是用户说的话）：上一轮以来，本对话的采集任务有这些变化。",
            "需要时告诉用户；数量以这里和工具结果为准。",
            *(_line(task) for task in changed),
        ]
    )


async def instructions(session: AsyncSession, conversation_id: int) -> str | None:
    """本轮要注入的全部说明，没有时返回 None。会更新已注入的快照，由调用方提交。"""
    from gleanery.agent.injection_reports import report_context

    parts = [
        await task_changes(session, conversation_id),
        await report_context(session, conversation_id),
    ]
    return "\n\n".join(part for part in parts if part) or None
