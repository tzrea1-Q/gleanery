"""本地服务命令。"""

import argparse
import asyncio
import contextlib
import errno
import os
import secrets
import socket
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlencode

import uvicorn

from gleanery.app import create_app
from gleanery.browser.manager import BrowserManager
from gleanery.clock import SystemClock
from gleanery.deps import AppDeps
from gleanery.events import EventBus
from gleanery.llm.chatgpt import ChatGPTPlan
from gleanery.llm.credentials import open_credential_store
from gleanery.llm.resolver import make_model_resolver
from gleanery.lock import InstanceLock
from gleanery.paths import data_directory
from gleanery.platforms.runtime import BrowserRuntime
from gleanery.platforms.types import ParsedCapture


class Server(uvicorn.Server):
    """开始关闭时先关事件总线。

    浏览器开着 `/api/events` 时 SSE 流不会自己结束，uvicorn 要等到优雅关闭超时才取消它，
    终端会打出 CancelledError 的回溯（2026-11-02 M1 冒烟）。先关总线，SSE 流随之正常结束。
    """

    def __init__(self, config: uvicorn.Config, events: EventBus) -> None:
        super().__init__(config)
        self.events = events

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        self.events.close()
        await super().shutdown(sockets)


def bind_port(port: int) -> socket.socket:
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # 刚退出时端口上还有 TIME_WAIT 连接，不设这个会换到随机端口
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server_socket.bind(("127.0.0.1", port))
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
            server_socket.bind(("127.0.0.1", 0))
        server_socket.listen(2048)
        return server_socket
    except BaseException:
        server_socket.close()
        raise


def launch_url(port: int, token: str) -> str:
    return f"http://127.0.0.1:{port}/auth/launch?{urlencode({'token': token})}"


def main() -> None:
    # pydantic-ai 首次运行会往终端打一段推广横幅，对本地应用没有用。
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    parser = argparse.ArgumentParser(prog="gleanery")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--static-dir", type=Path, default=Path(__file__).resolve().parents[2] / "frontend/dist"
    )
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--dev-origin", action="append", default=[])
    subcommands = parser.add_subparsers(dest="command")
    fixture = subcommands.add_parser("fixture")
    fixture_commands = fixture.add_subparsers(dest="fixture_command", required=True)
    export = fixture_commands.add_parser("export")
    export.add_argument("--task", type=int, required=True)
    export.add_argument("--kind", required=True)
    export.add_argument("--case", required=True)
    export.add_argument("--index", type=int, default=0)
    export.add_argument("--trim", type=int)
    reparse = subcommands.add_parser("reparse")
    reparse.add_argument("--task", type=int, required=True)
    args = parser.parse_args()
    if args.command:
        try:
            asyncio.run(_run_command(args))
        except (ValueError, FileNotFoundError, FileExistsError, NotImplementedError) as exc:
            parser.exit(1, f"错误：{exc}\n")
        return
    if not 0 <= args.port <= 65535:
        parser.error("端口必须在 0 到 65535 之间")
    data_dir = data_directory()
    lock = InstanceLock(data_dir)
    try:
        server_socket = bind_port(args.port)
    except BaseException:
        lock.close()
        raise
    try:
        port = server_socket.getsockname()[1]
        token = secrets.token_urlsafe(32)
        if not lock.acquire(port, token):
            instance = lock.read()
            print("Gleanery 已在运行")
            if not args.no_browser:
                webbrowser.open(launch_url(instance["port"], instance["token"]))
            raise SystemExit(1)
        static_dir = args.static_dir if args.static_dir.is_dir() else None
        if static_dir is None:
            print("未找到前端构建产物，只启动 API。")
        credential_store = open_credential_store(data_dir)
        clock = SystemClock()
        chatgpt = ChatGPTPlan(credential_store, clock, port)
        deps = AppDeps(
            data_dir=data_dir,
            launch_token=token,
            port=port,
            clock=clock,
            model_resolver=make_model_resolver(credential_store, chatgpt=chatgpt),
            credential_store=credential_store,
            chatgpt=chatgpt,
            static_dir=static_dir,
            extra_origins=frozenset(args.dev_origin),
            platform_runtime=BrowserRuntime(BrowserManager(data_dir, clock), clock),
        )
        app = create_app(deps)
        server = Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                access_log=False,
                # 兜底：总线关了之后仍没断开的长连接，最多等 3 秒。
                timeout_graceful_shutdown=3,
            ),
            app.state.events,
        )
        if not args.no_browser:

            def open_when_ready() -> None:
                while not server.started and not server.should_exit:
                    time.sleep(0.05)
                if server.started:
                    webbrowser.open(launch_url(port, token))

            threading.Thread(target=open_when_ready, daemon=True).start()
        # uvicorn 优雅关闭后会把 Ctrl-C 再抛一次，uvicorn.run 也是这样吞掉的
        with contextlib.suppress(KeyboardInterrupt):
            server.run(sockets=[server_socket])
    finally:
        server_socket.close()
        lock.close()


async def _run_command(args: argparse.Namespace) -> None:
    from gleanery.fixtures.export import export_fixture
    from gleanery.platforms.registry import parser_for
    from gleanery.store.db import DB_FILENAME, open_database
    from gleanery.store.repo_raw_capture import decompress, list_for_task

    data_dir = data_directory()
    if not (data_dir / DB_FILENAME).is_file():
        raise FileNotFoundError("未找到内容库")
    db = await open_database(data_dir)
    try:
        async with db.sessionmaker() as session:
            if args.command == "fixture":
                path = await export_fixture(
                    session, args.task, args.kind, args.case, args.index, args.trim
                )
                print(f"已导出 {path}")
            else:
                rows = await list_for_task(session, args.task)
                parsed = []
                for row in rows:
                    capture = decompress(row)
                    result = parser_for(capture.platform)(capture)
                    if result is not None:
                        parsed.append(result)
                _save_reparsed(parsed)
                print(
                    f"原始响应 {len(rows)} 条，解析产出 {len(parsed)} 条，条目 {sum(item.report.items for item in parsed)} 条；尚未写入内容库。"
                )
    finally:
        await db.close()


def _save_reparsed(parsed: list[ParsedCapture]) -> None:
    """TODO: 内容库仓储完成后，将解析产出合并写入内容库。"""
