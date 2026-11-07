import os
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gleanery.app import create_app
from gleanery.cli import bind_port
from gleanery.clock import SystemClock
from gleanery.deps import AppDeps
from gleanery.lock import InstanceLock
from gleanery.paths import data_directory
from tests.support.memory import MemoryCredentialStore, no_model


@pytest.fixture
def client(tmp_path: Path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("首页")
    (static / "assets" / "app.js").write_text("asset")
    deps = AppDeps(
        data_dir=tmp_path,
        launch_token="secret",
        port=8765,
        clock=SystemClock(),
        model_resolver=no_model,
        credential_store=MemoryCredentialStore(),
        static_dir=static,
        extra_origins=frozenset({"http://127.0.0.1:5173"}),
    )
    with TestClient(create_app(deps), base_url="http://127.0.0.1:8765") as client:
        yield client


def test_host_and_origin(client: TestClient) -> None:
    assert client.get("/", headers={"host": "evil.test"}).json()["code"] == "BAD_HOST"
    for host in ("localhost:8765", "127.0.0.1:8765", "127.0.0.1:5173"):
        assert (
            client.get("/", headers={"host": host, "origin": "http://evil.test"}).status_code == 200
        )
    for origin in (None, "http://evil.test"):
        headers = {} if origin is None else {"origin": origin}
        response = client.post("/api/conversations", headers=headers)
        assert (response.status_code, response.json()["code"]) == (403, "BAD_ORIGIN")
    for origin in ("http://localhost:8765", "http://127.0.0.1:8765", "http://127.0.0.1:5173"):
        assert client.post("/api/conversations", headers={"origin": origin}).status_code == 401


def test_session_and_launch(client: TestClient) -> None:
    assert client.get("/api/conversations").json()["code"] == "NO_SESSION"
    client.cookies.set("gleanery_session", "bad")
    assert client.get("/api/conversations").status_code == 401
    assert client.get("/auth/launch?token=bad").status_code == 403
    for destination in ("//evil.com", "https://evil.com", "/\\evil.com"):
        response = client.get(
            "/auth/launch", params={"token": "secret", "next": destination}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
    assert client.get("/api/conversations").status_code == 200
    # ApiError 经全部中间件后仍以 ErrorBody 返回。
    response = client.get("/api/conversations/999")
    assert response.status_code == 404
    assert response.json()["code"] == "CONVERSATION_NOT_FOUND"


def test_static(client: TestClient) -> None:
    assert client.get("/assets/app.js").text == "asset"
    assert client.get("/some/page").text == "首页"
    assert client.get("/some/page").headers["cache-control"] == "no-cache"
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/index.html").headers["cache-control"] == "no-cache"
    assert "cache-control" not in client.get("/assets/app.js").headers
    client.get("/auth/launch?token=secret")
    assert client.get("/api/missing").status_code == 404
    assert client.get("/auth/missing").status_code == 404


def test_lock(tmp_path: Path) -> None:
    first, second = InstanceLock(tmp_path), InstanceLock(tmp_path)
    try:
        assert first.acquire(1234, "secret")
        assert not second.acquire(5678, "other")
        assert second.read() == {"pid": os.getpid(), "port": 1234, "token": "secret"}
        assert (tmp_path / "gleanery.lock").stat().st_mode & 0o777 == 0o600
    finally:
        second.close()
        first.close()


def test_port() -> None:
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        with bind_port(occupied.getsockname()[1]) as selected:
            assert selected.getsockname()[1] != occupied.getsockname()[1]


def test_port_reused_after_restart() -> None:
    with bind_port(0) as listener:
        port = listener.getsockname()[1]
        client = socket.create_connection(("127.0.0.1", port))
        accepted, _ = listener.accept()
        accepted.close()  # 服务端先关，连接留在 TIME_WAIT
        client.close()
    with bind_port(port) as again:
        assert again.getsockname()[1] == port


def test_data_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLEANERY_DATA_DIR", str(tmp_path / "data"))
    path = data_directory()
    assert path == tmp_path / "data"
    assert path.stat().st_mode & 0o777 == 0o700
