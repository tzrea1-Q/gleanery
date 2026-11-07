from pathlib import Path

import httpx2
from fastapi.testclient import TestClient
from pydantic_ai.models import override_allow_model_requests

from gleanery.app import create_app
from gleanery.clock import SystemClock
from gleanery.deps import AppDeps
from gleanery.llm.credentials import FileCredentialStore
from gleanery.llm.resolver import make_model_resolver
from tests.support.fake_openai import fake_openai


def test_model_flow(tmp_path: Path) -> None:
    store = FileCredentialStore(tmp_path)
    transport = httpx2.ASGITransport(app=fake_openai())
    deps = AppDeps(
        data_dir=tmp_path,
        launch_token="session",
        port=8765,
        clock=SystemClock(),
        credential_store=store,
        model_resolver=make_model_resolver(store, transport),
        llm_transport=transport,
    )
    with (
        TestClient(
            create_app(deps),
            base_url="http://127.0.0.1:8765",
            headers={"origin": "http://127.0.0.1:8765"},
            cookies={"gleanery_session": "session"},
        ) as client,
        override_allow_model_requests(True),
    ):
        key = "secret-test-key-123"
        responses = []
        responses.append(
            client.post(
                "/api/model-configs",
                json={
                    "name": "本地",
                    "preset": "custom",
                    "base_url": "http://fake/v1",
                    "api_key": key,
                },
            )
        )
        assert responses[-1].status_code == 201, responses[-1].text
        config_id = responses[-1].json()["id"]
        assert responses[-1].json()["available_models"] == ["fake-model"]
        responses.append(
            client.post(f"/api/model-configs/{config_id}/favorites", json={"model": "fake-model"})
        )
        assert responses[-1].json()["favorites"][0]["tool_test"] == "ok", responses[-1].text
        responses.append(
            client.put(
                "/api/app-state/current-model", json={"config_id": config_id, "model": "fake-model"}
            )
        )
        assert responses[-1].status_code == 200
        responses.append(client.get("/api/model-configs"))
        responses.append(client.delete(f"/api/model-configs/{config_id}/favorites/fake-model"))
        responses.append(client.get("/api/app-state"))
        assert responses[-1].json()["current_model"] is None
        assert all(key not in response.text for response in responses)
        for path in tmp_path.glob("gleanery.db*"):
            assert key.encode() not in path.read_bytes()


def test_probe_failures(tmp_path: Path) -> None:
    for status, no_tool, missing_models, expected_status, expected_error in [
        (401, False, False, "unavailable", "上游 401"),
        (429, False, False, "unavailable", "上游 429"),
        (200, True, False, "ok", "模型没有调用工具"),
        (200, False, True, "ok", None),
    ]:
        store = FileCredentialStore(tmp_path / str(status) / str(no_tool) / str(missing_models))
        store.path.parent.mkdir(parents=True)
        transport = httpx2.ASGITransport(app=fake_openai(status, no_tool, missing_models))
        deps = AppDeps(
            data_dir=store.path.parent,
            launch_token="session",
            port=8765,
            clock=SystemClock(),
            credential_store=store,
            model_resolver=make_model_resolver(store, transport),
            llm_transport=transport,
        )
        with (
            TestClient(
                create_app(deps),
                base_url="http://127.0.0.1:8765",
                headers={"origin": "http://127.0.0.1:8765"},
                cookies={"gleanery_session": "session"},
            ) as client,
            override_allow_model_requests(True),
        ):
            created = client.post(
                "/api/model-configs",
                json={"name": "本地", "preset": "custom", "base_url": "http://fake/v1"},
            ).json()
            assert created["status"] == expected_status
            if missing_models:
                assert created["available_models"] is None
            result = client.post(
                f"/api/model-configs/{created['id']}/favorites", json={"model": "fake-model"}
            ).json()
            error = result["favorites"][0]["tool_test_error"]
            assert error == expected_error or error.startswith(f"{expected_error}：")
            selected = client.put(
                "/api/app-state/current-model",
                json={"config_id": created["id"], "model": "fake-model"},
            )
            assert selected.status_code == (200 if expected_error is None else 409)


def test_edit_keeps_tool_tests_unless_base_url_changes(tmp_path: Path) -> None:
    store = FileCredentialStore(tmp_path)
    transport = httpx2.ASGITransport(app=fake_openai())
    deps = AppDeps(
        data_dir=tmp_path,
        launch_token="session",
        port=8765,
        clock=SystemClock(),
        credential_store=store,
        model_resolver=make_model_resolver(store, transport),
        llm_transport=transport,
    )
    with (
        TestClient(
            create_app(deps),
            base_url="http://127.0.0.1:8765",
            headers={"origin": "http://127.0.0.1:8765"},
            cookies={"gleanery_session": "session"},
        ) as client,
        override_allow_model_requests(True),
    ):
        base = "http://fake/v1"
        body = {"name": "本地", "preset": "custom", "base_url": base, "api_key": "k1"}
        config_id = client.post("/api/model-configs", json=body).json()["id"]
        client.post(f"/api/model-configs/{config_id}/favorites", json={"model": "fake-model"})
        selected = {"config_id": config_id, "model": "fake-model"}
        assert client.put("/api/app-state/current-model", json=selected).status_code == 200

        # 前端编辑时会原样带上 base_url；只换 Key 不重置工具调用测试。
        edited = client.patch(
            f"/api/model-configs/{config_id}", json={"base_url": base, "api_key": "k2"}
        ).json()
        assert edited["favorites"][0]["tool_test"] == "ok"
        current = client.get("/api/app-state").json()["current_model"]
        assert (current["status"], current["status_reason"]) == ("ok", None)

        client.patch(f"/api/model-configs/{config_id}", json={"base_url": "http://fake/v2"})
        current = client.get("/api/app-state").json()["current_model"]
        assert current["status"] == "unavailable"
        assert current["status_reason"] == "需要重新测试工具调用"
