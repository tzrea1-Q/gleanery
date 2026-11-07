from __future__ import annotations

import asyncio
import os
import socket
from contextlib import suppress
from pathlib import Path
from typing import Protocol

from playwright.async_api import Browser, Playwright, async_playwright

from gleanery.browser.finder import BrowserExecutable
from gleanery.platforms.errors import BrowserDisconnected, ProfileInUse


class Process(Protocol):
    @property
    def pid(self) -> int: ...

    @property
    def returncode(self) -> int | None: ...

    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    async def wait(self) -> int: ...


class ProcessFactory(Protocol):
    async def __call__(self, args: list[str]) -> Process: ...


class Connection(Protocol):
    browser: Browser

    async def close(self) -> None: ...


class ConnectionFactory(Protocol):
    async def __call__(self, endpoint: str) -> Connection: ...


async def start_process(args: list[str]) -> Process:
    return await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )


class PlaywrightConnection:
    def __init__(self, playwright: Playwright, browser: Browser) -> None:
        self.playwright = playwright
        self.browser = browser

    async def close(self) -> None:
        try:
            await self.browser.close()
        finally:
            await self.playwright.stop()


async def connect(endpoint: str) -> Connection:
    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
    except BaseException:
        await playwright.stop()
        raise
    return PlaywrightConnection(playwright, browser)


def check_profile(profile: Path) -> None:
    lock = profile / "SingletonLock"
    try:
        target = os.readlink(lock)
    except FileNotFoundError:
        return
    except OSError:
        raise ProfileInUse("无法确认浏览器配置目录锁的状态") from None
    host, separator, pid_text = target.rpartition("-")
    if (
        not separator
        or not pid_text.isdecimal()
        or int(pid_text) <= 0
        or host != socket.gethostname()
    ):
        raise ProfileInUse("无法确认浏览器配置目录锁的归属")
    try:
        os.kill(int(pid_text), 0)
    except ProcessLookupError:
        return
    except PermissionError:
        pass
    raise ProfileInUse("浏览器配置目录已被其他进程占用")


async def stop_process(process: Process) -> None:
    if process.returncode is not None:
        return
    with suppress(ProcessLookupError):
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), 5)
    except TimeoutError:
        with suppress(ProcessLookupError):
            process.kill()
        await process.wait()


def prepare_profile(profile: Path) -> None:
    profile.mkdir(mode=0o700, parents=True, exist_ok=True)
    profile.chmod(0o700)
    check_profile(profile)
    (profile / "DevToolsActivePort").unlink(missing_ok=True)


async def launch(
    executable: BrowserExecutable,
    profile: Path,
    process_factory: ProcessFactory,
    connection_factory: ConnectionFactory,
) -> tuple[Process, Connection]:
    await asyncio.to_thread(prepare_profile, profile)
    port_file = profile / "DevToolsActivePort"
    process = await process_factory(
        [
            str(executable.path),
            f"--user-data-dir={profile}",
            "--remote-debugging-port=0",
            "--no-first-run",
            "--no-default-browser-check",
        ]
    )
    try:
        # 全新配置目录首次启动要做初始化，20 秒不够。
        async with asyncio.timeout(60):
            while True:
                if process.returncode is not None:
                    raise BrowserDisconnected("浏览器启动时退出")
                try:
                    port = int(port_file.read_text().splitlines()[0])
                    if not 1 <= port <= 65535:
                        raise ValueError
                    break
                except (FileNotFoundError, IndexError, ValueError):
                    await asyncio.sleep(0.05)
            connection = await connection_factory(f"http://127.0.0.1:{port}")
            if process.returncode is not None or not connection.browser.is_connected():
                await connection.close()
                raise BrowserDisconnected("浏览器启动时断开")
        return process, connection
    except BaseException:
        await stop_process(process)
        raise
