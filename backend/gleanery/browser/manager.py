from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Page

from gleanery.browser.finder import BrowserExecutable, BrowserKind, find_browser
from gleanery.browser.launcher import (
    Connection,
    ConnectionFactory,
    Process,
    ProcessFactory,
    connect,
    launch,
    start_process,
    stop_process,
)
from gleanery.deps import Clock
from gleanery.platforms.errors import BrowserDisconnected
from gleanery.platforms.types import Platform


@dataclass
class _Session:
    process: Process
    connection: Connection
    kind: BrowserKind
    users: dict[asyncio.Task[object], int] = field(default_factory=dict)
    idle: asyncio.Task[None] | None = None
    watcher: asyncio.Task[None] | None = None
    disconnected: bool = False
    closing: bool = False


class BrowserManager:
    def __init__(
        self,
        data_dir: Path,
        clock: Clock,
        *,
        process_factory: ProcessFactory = start_process,
        connection_factory: ConnectionFactory = connect,
        browser_finder: Callable[[], Awaitable[BrowserExecutable]] = find_browser,
    ) -> None:
        self.data_dir = data_dir
        self.clock = clock
        self.process_factory = process_factory
        self.connection_factory = connection_factory
        self.browser_finder = browser_finder
        self._sessions: dict[Platform, _Session] = {}
        self._locks: dict[Platform, asyncio.Lock] = {}

    def is_running(self, platform: Platform) -> bool:
        session = self._sessions.get(platform)
        return bool(
            session
            and not session.disconnected
            and session.process.returncode is None
            and session.connection.browser.is_connected()
        )

    def browser_kind(self, platform: Platform) -> BrowserKind | None:
        session = self._sessions.get(platform)
        return session.kind if session and self.is_running(platform) else None

    def _disconnect(self, session: _Session) -> None:
        if session.closing or session.disconnected:
            return
        session.disconnected = True
        for task in session.users:
            task.cancel()

    async def _watch(self, session: _Session) -> None:
        await session.process.wait()
        self._disconnect(session)

    async def _close(self, session: _Session) -> None:
        session.closing = True
        if session.idle and session.idle is not asyncio.current_task():
            session.idle.cancel()
        if session.watcher:
            session.watcher.cancel()
        try:
            await session.connection.close()
        finally:
            await stop_process(session.process)

    async def _idle_close(self, platform: Platform, session: _Session) -> None:
        await self.clock.sleep(900)
        async with self._locks[platform]:
            if self._sessions.get(platform) is session and not session.users:
                del self._sessions[platform]
                await self._close(session)

    @asynccontextmanager
    async def page(self, platform: Platform) -> AsyncIterator[Page]:
        if platform not in ("bili", "xhs"):
            raise ValueError("未知平台")
        lock = self._locks.setdefault(platform, asyncio.Lock())
        task = asyncio.current_task()
        assert task is not None
        async with lock:
            session = self._sessions.get(platform)
            if session and not self.is_running(platform):
                del self._sessions[platform]
                self._disconnect(session)
                await self._close(session)
                session = None
            if session is None:
                executable = await self.browser_finder()
                process, connection = await launch(
                    executable,
                    self.data_dir / "profiles" / platform,
                    self.process_factory,
                    self.connection_factory,
                )
                session = _Session(process, connection, executable.kind)
                self._sessions[platform] = session
                connection.browser.on("disconnected", lambda _: self._disconnect(session))
                session.watcher = asyncio.create_task(self._watch(session))
            if session.idle:
                session.idle.cancel()
                session.idle = None
            session.users[task] = session.users.get(task, 0) + 1
        page: Page | None = None
        try:
            page = await session.connection.browser.contexts[0].new_page()
            yield page
        except asyncio.CancelledError:
            if session.disconnected:
                raise BrowserDisconnected("浏览器连接已断开") from None
            raise
        except Exception as error:
            if session.disconnected or not self.is_running(platform):
                raise BrowserDisconnected("浏览器连接已断开") from error
            # 用户关掉了这个标签页（扫完码顺手关窗口很常见）：浏览器还在，但这一页的操作都会失败。
            # 按断开处理，任务暂停等用户点继续，而不是当成网络错误判失败。
            if page is not None and page.is_closed():
                raise BrowserDisconnected("页面被关闭") from error
            raise
        finally:
            if page is not None:
                with suppress(Exception):
                    await page.close()
            async with lock:
                session.users[task] -= 1
                if session.users[task] == 0:
                    del session.users[task]
                if (
                    not session.users
                    and self._sessions.get(platform) is session
                    and not session.closing
                ):
                    session.idle = asyncio.create_task(self._idle_close(platform, session))

    async def close_all(self) -> None:
        for platform in list(self._locks):
            async with self._locks[platform]:
                session = self._sessions.pop(platform, None)
                if session:
                    self._disconnect(session)
                    await self._close(session)
