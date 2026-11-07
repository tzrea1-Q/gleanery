from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path
from typing import Any, cast

import pytest

from gleanery.browser.finder import BrowserExecutable
from gleanery.browser.launcher import check_profile
from gleanery.browser.manager import BrowserManager
from gleanery.platforms.errors import BrowserDisconnected, ProfileInUse


class FakeClock:
    def __init__(self) -> None:
        self.waiters: list[asyncio.Future[None]] = []

    def now_ms(self) -> int:
        return 0

    async def sleep(self, seconds: float) -> None:
        assert seconds == 900
        future = asyncio.get_running_loop().create_future()
        self.waiters.append(future)
        await future


class FakeProcess:
    def __init__(self) -> None:
        self.pid = 12345
        self.returncode: int | None = None
        self.done = asyncio.Event()

    def terminate(self) -> None:
        self.exit()

    def kill(self) -> None:
        self.exit()

    def exit(self) -> None:
        self.returncode = 0
        self.done.set()

    async def wait(self) -> int:
        await self.done.wait()
        return 0


class FakePage:
    def __init__(self) -> None:
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self) -> None:
        self.connected = True
        self.contexts = [self]
        self.callback: Any = None

    async def new_page(self) -> FakePage:
        return FakePage()

    def on(self, event: str, callback: Any) -> None:
        assert event == "disconnected"
        self.callback = callback

    def is_connected(self) -> bool:
        return self.connected

    def disconnect(self) -> None:
        self.connected = False
        self.callback(self)


class Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.clock = FakeClock()
        self.processes: list[FakeProcess] = []
        self.browsers: list[FakeBrowser] = []
        self.args: list[list[str]] = []
        self.manager = BrowserManager(
            tmp_path,
            self.clock,
            process_factory=self.process,
            connection_factory=self.connect,
            browser_finder=self.find,
        )

    async def find(self) -> BrowserExecutable:
        return BrowserExecutable(Path("/fake/chromium"), "chromium")

    async def process(self, args: list[str]) -> Any:
        self.args.append(args)
        profile = Path(
            next(
                arg.removeprefix("--user-data-dir=")
                for arg in args
                if arg.startswith("--user-data-dir=")
            )
        )
        (profile / "DevToolsActivePort").write_text("1234\n/devtools/browser/test\n")
        process = FakeProcess()
        self.processes.append(process)
        return process

    async def connect(self, endpoint: str) -> Any:
        assert endpoint == "http://127.0.0.1:1234"
        browser = FakeBrowser()
        self.browsers.append(browser)

        class Connection:
            async def close(self) -> None:
                browser.connected = False

        connection = Connection()
        connection.browser = browser  # type: ignore[attr-defined]
        return connection


async def test_concurrent_and_idle(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    manager = harness.manager
    entered = asyncio.Event()
    release = asyncio.Event()
    count = 0

    async def use() -> None:
        nonlocal count
        async with manager.page("bili"):
            count += 1
            if count == 2:
                entered.set()
            await release.wait()

    tasks = [asyncio.create_task(use()) for _ in range(2)]
    await entered.wait()
    assert len(harness.processes) == 1
    assert manager.browser_kind("bili") == "chromium"
    args = harness.args[0]
    assert "--remote-debugging-port=0" in args
    assert any(arg.startswith("--user-data-dir=") for arg in args)
    assert not {"--use-mock-keychain", "--password-store=basic", "--headless"} & set(args)
    assert (tmp_path / "profiles/bili").stat().st_mode & 0o777 == 0o700
    release.set()
    await asyncio.gather(*tasks)
    await asyncio.sleep(0)
    idle = manager._sessions["bili"].idle
    assert idle is not None
    harness.clock.waiters[-1].set_result(None)
    await idle
    await manager.close_all()
    assert harness.processes[0].returncode == 0


@pytest.mark.parametrize("how", ["process", "cdp"])
async def test_disconnect_restarts(tmp_path: Path, how: str) -> None:
    harness = Harness(tmp_path)
    ready = asyncio.Event()

    async def use() -> None:
        async with harness.manager.page("xhs"):
            ready.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(use())
    await ready.wait()
    if how == "process":
        harness.processes[0].exit()
    else:
        harness.browsers[0].disconnect()
    with pytest.raises(BrowserDisconnected):
        await task
    async with harness.manager.page("xhs"):
        assert len(harness.processes) == 2
    await harness.manager.close_all()
    assert all(process.returncode is not None for process in harness.processes)


def test_profile_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = tmp_path / "SingletonLock"
    lock.symlink_to(f"{socket.gethostname()}-{os.getpid()}")
    with pytest.raises(ProfileInUse):
        check_profile(tmp_path)
    lock.unlink()
    lock.symlink_to(f"{socket.gethostname()}-99999999")

    def dead(pid: int, signal: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(os, "kill", dead)
    check_profile(tmp_path)


async def test_failed_connection_stops_process(tmp_path: Path) -> None:
    harness = Harness(tmp_path)

    async def fail(endpoint: str) -> Any:
        raise RuntimeError("连接失败")

    harness.manager.connection_factory = fail
    with pytest.raises(RuntimeError, match="连接失败"):
        async with harness.manager.page("bili"):
            pass
    assert harness.processes[0].returncode == 0
    assert not harness.manager.is_running("bili")


async def test_reuse_cancels_idle_and_close_all(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    async with harness.manager.page("bili"):
        pass
    await asyncio.sleep(0)
    first_waiter = harness.clock.waiters[-1]
    async with harness.manager.page("bili"):
        assert len(harness.processes) == 1
        assert first_waiter.cancelled() or not first_waiter.done()
    async with harness.manager.page("xhs"):
        pass
    await harness.manager.close_all()
    assert all(process.returncode is not None for process in harness.processes)


async def test_closed_page_counts_as_disconnected(tmp_path: Path) -> None:
    # 浏览器还在、只有这一页被用户关掉时，按断开处理；页面没关时原样抛出。
    harness = Harness(tmp_path)
    with pytest.raises(BrowserDisconnected, match="页面被关闭"):
        async with harness.manager.page("bili") as page:
            cast(FakePage, page).closed = True
            raise RuntimeError("Target page, context or browser has been closed")
    with pytest.raises(RuntimeError, match="别的错误"):
        async with harness.manager.page("bili"):
            raise RuntimeError("别的错误")
    assert harness.manager.is_running("bili")
    await harness.manager.close_all()
