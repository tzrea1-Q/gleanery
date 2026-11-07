import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.e2e.app_factory import build_e2e_deps, create_e2e_app
from tests.e2e.seed import seed


def test_e2e_factory(tmp_path: Path) -> None:
    asyncio.run(seed(tmp_path))
    deps = build_e2e_deps(tmp_path, static_dir=tmp_path)
    with TestClient(create_e2e_app(deps), base_url="http://127.0.0.1:8799") as client:
        client.get("/auth/launch", params={"token": deps.launch_token}, follow_redirects=False)
        client.headers["origin"] = "http://127.0.0.1:8799"
        state = client.get("/api/app-state").json()
        assert state["current_model"]["model"] == "e2e-model"
        assert state["disclaimer_acknowledged"] is False
        cid = client.post("/api/conversations").json()["id"]
        response = client.post(
            "/api/chat",
            json={
                "id": str(cid),
                "trigger": "submit-message",
                "messages": [
                    {"id": "one", "role": "user", "parts": [{"type": "text", "text": "你好"}]}
                ],
            },
        )
        assert response.status_code == 200
        assert "收到：" in response.text and "你好" in response.text


def _events(text: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in text.splitlines()
        if line.startswith("data: {")
    ]


@pytest.mark.parametrize("risky", [False, True])
def test_e2e_collection_flow(tmp_path: Path, risky: bool) -> None:
    """e2e 基建自检：脚本模型起草计划 → 审批 → 回放取数器执行 → 数据集出行。"""
    asyncio.run(seed(tmp_path))
    deps = build_e2e_deps(tmp_path, static_dir=tmp_path)
    with TestClient(create_e2e_app(deps), base_url="http://127.0.0.1:8799") as client:
        client.get("/auth/launch", params={"token": deps.launch_token}, follow_redirects=False)
        client.headers["origin"] = "http://127.0.0.1:8799"
        cid = str(client.post("/api/conversations").json()["id"])

        def say(message_id: str, text: str) -> list[dict]:
            response = client.post(
                "/api/chat",
                json={
                    "id": cid,
                    "trigger": "submit-message",
                    "messages": [
                        {
                            "id": message_id,
                            "role": "user",
                            "parts": [{"type": "text", "text": text}],
                        }
                    ],
                },
            )
            assert response.status_code == 200, response.text
            return _events(response.text)

        events = say("u1", "采集一些风控视频" if risky else "采集一些咖啡视频")
        assert any(e.get("toolName") == "propose_collection_plan" for e in events)
        plans = client.get("/api/plans", params={"conversation_id": cid}).json()
        assert [item["id"] for item in plans] == [1]
        plan = client.get("/api/plans/1").json()
        assert plan["status"] == "draft" and plan["issues"] == []

        events = say("u2", "开始吧")
        request = next(e for e in events if e["type"] == "tool-approval-request")
        response = client.post(
            "/api/chat",
            json={
                "id": cid,
                "trigger": "submit-message",
                "messages": [
                    {
                        "id": "a2",
                        "role": "assistant",
                        "parts": [
                            {
                                "type": "tool-start_collection",
                                "toolCallId": request["toolCallId"],
                                "state": "approval-responded",
                                "input": {"plan_id": 1},
                                "approval": {"id": request["approvalId"], "approved": True},
                            }
                        ],
                    }
                ],
            },
        )
        assert "采集已开始" in response.text, response.text

        tasks: list[dict] = []
        for _ in range(100):
            tasks = client.get("/api/tasks", params={"plan_id": 1}).json()
            if tasks and tasks[0]["status"] not in ("queued", "running"):
                break
            time.sleep(0.05)

        def reply(events: list[dict]) -> str:
            return "".join(e.get("delta", "") for e in events if e.get("type") == "text-delta")

        # 任务结束（或风控暂停）后追加事件消息，变化由它告诉模型，不再重复注入。
        event: dict = {}
        for _ in range(100):
            messages = client.get(f"/api/conversations/{cid}").json()["messages"]
            event = next(
                (m for m in messages if (m.get("metadata") or {}).get("gleanery_event")), {}
            )
            if event:
                break
            time.sleep(0.05)
        text = event["parts"][0]["text"]
        assert "task_id=1" in text and text.startswith("系统事件")
        assert ("触发风控" in text) is risky
        assert event["metadata"]["gleanery_event"]["type"] == (
            "collection_paused" if risky else "collection_finished"
        )
        assert reply(say("u3", "进度呢")) == "没有新的任务变化"
        if risky:
            assert (tasks[0]["status"], tasks[0]["reason"]) == ("paused", "risk"), tasks
            platform = next(
                p for p in client.get("/api/platforms").json() if p["platform"] == "bili"
            )
            assert platform["state"] == "cooldown"
            assert client.get("/api/risk-events").json()[0]["outcome"] == "cooldown"
            return
        assert tasks[0]["status"] == "completed", tasks
        assert tasks[0]["progress"]["processed"] == 3
        assert tasks[0]["progress"]["eta_seconds"] == 0
        dataset = client.get(f"/api/datasets/{tasks[0]['dataset_id']}/contents").json()
        assert dataset["total"] == 3
        assert all(row["completeness"] == "detail" for row in dataset["items"])
