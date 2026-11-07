import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from gleanery.app import create_app
from gleanery.cli import Server
from gleanery.clock import SystemClock
from gleanery.deps import AppDeps
from tests.support.memory import MemoryCredentialStore


async def no_model(session):
    return None


@pytest.mark.slow
async def test_shutdown_ends_open_sse_stream(tmp_path: Path) -> None:
    """开着 SSE 时退出，不等优雅关闭超时（2026-11-02 M1 冒烟的观察）。"""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = create_app(
        AppDeps(
            data_dir=tmp_path,
            launch_token="secret",
            port=port,
            clock=SystemClock(),
            model_resolver=no_model,
            credential_store=MemoryCredentialStore(),
        )
    )
    server = Server(
        uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=10),
        app.state.events,
    )
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:  # noqa: ASYNC110  uvicorn 没有"已启动"的事件可等
        await asyncio.sleep(0.01)
    async with (
        httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", cookies={"gleanery_session": "secret"}
        ) as client,
        client.stream("GET", "/api/events") as response,
    ):
        assert response.status_code == 200
        started = time.monotonic()
        server.should_exit = True
        await asyncio.wait_for(serving, timeout=5)
        assert time.monotonic() - started < 3


@pytest.mark.slow
def test_ctrl_c_exits_without_traceback(tmp_path: Path) -> None:
    """终端里按 Ctrl-C：正常退出，不打印 KeyboardInterrupt 的回溯（M2-13）。"""
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; from gleanery.cli import main;"
            " sys.argv = ['gleanery', '--no-browser', '--port', '0']; main()",
        ],
        env={**os.environ, "GLEANERY_DATA_DIR": str(tmp_path)},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # 端口在 uvicorn 接管信号之前就已监听，要等启动完成的日志再发 Ctrl-C
    assert process.stdout is not None
    lines: list[str] = []
    while "Application startup complete" not in (lines[-1] if lines else ""):
        line = process.stdout.readline()
        assert line, "".join(lines)
        lines.append(line)
    process.send_signal(signal.SIGINT)
    rest, _ = process.communicate(timeout=10)
    output = "".join(lines) + rest
    assert "Finished server process" in output
    assert "Traceback" not in output
