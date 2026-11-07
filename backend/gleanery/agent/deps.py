"""Agent 工具的依赖。每轮由 `api/chat.py` 构造。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import tzinfo
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gleanery.collect.service import CollectService
from gleanery.deps import Clock
from gleanery.events import EventBus
from gleanery.query.sql import ReadOnlySql


@dataclass(frozen=True)
class AgentDeps:
    sessionmaker: async_sessionmaker[AsyncSession]
    """工具各自开会话、各自提交，不与对话消息的会话共用。"""
    conversation_id: int
    clock: Clock
    events: EventBus
    collect: CollectService
    sql: ReadOnlySql
    tz: tzinfo | None
    """查询工具输出本地时间用；None 为本机时区。"""
    data_dir: Path


def agent_deps(app: FastAPI, conversation_id: int) -> AgentDeps:
    """由 `app.state` 构造一轮的依赖。对话路由与后台续跑共用。"""
    deps = app.state.deps
    return AgentDeps(
        app.state.db.sessionmaker,
        conversation_id,
        deps.clock,
        app.state.events,
        app.state.collect,
        app.state.sql,
        deps.tz,
        deps.data_dir,
    )
