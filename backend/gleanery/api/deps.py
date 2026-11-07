from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.collect.login import LoginCoordinator
from gleanery.collect.service import CollectService
from gleanery.deps import AppDeps
from gleanery.events import EventBus


def get_deps(request: Request) -> AppDeps:
    return request.app.state.deps


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.db.sessionmaker() as session:
        yield session


def get_events(request: Request) -> EventBus:
    return request.app.state.events


def get_collect(request: Request) -> CollectService:
    return request.app.state.collect


def get_login(request: Request) -> LoginCoordinator:
    return request.app.state.login
