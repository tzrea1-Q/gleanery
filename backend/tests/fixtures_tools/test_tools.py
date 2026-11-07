import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from gleanery.cli import _run_command
from gleanery.fixtures.export import export_fixture
from gleanery.fixtures.leak import scan
from gleanery.fixtures.redact import redact
from gleanery.fixtures.update import update
from gleanery.platforms.types import Capture, ParsedCapture, ParseReport
from gleanery.store.db import open_database
from gleanery.store.models import CollectionTask, Dataset
from gleanery.store.repo_raw_capture import RawCaptureSink, decompress, get, list_for_task


def sample() -> Capture:
    return Capture(
        platform="bili",
        kind="x/v2/reply/wbi/main",
        url_path="/x/v2/reply/wbi/main",
        captured_at=1700000000000,
        headers={"Verifytype": "risk", "Set-Cookie": "secret"},
        query={"w_rid": "secret", "oid": "42", "mid": "123456"},
        body={
            "pagination_str": "secretcursor",
            "cursor": {"is_end": False, "pagination_reply": {"next_offset": "secret"}},
            "replies": [
                {
                    "rpid": 45,
                    "root": 12,
                    "parent": 13,
                    "mid": 123456,
                    "member": {
                        "mid": "123456",
                        "uname": "小明",
                        "avatar": "https://i.hdslb.com/bfs/face/abc",
                    },
                    "content": {
                        "message": "你好 @小明 [doge]\n这是测试文字",
                        "at_name_to_mid": {"小明": 123456},
                        "jump_url": {"测试文字": {"title": "测试文字"}, "BV1xx411c7mD": {}},
                    },
                    "unknown": "秘密" * 20,
                    "reply_control": {"location": "IP属地：江苏"},
                }
            ],
        },
    )


def test_redaction() -> None:
    source = sample()
    output = redact(source, salt="salt")
    assert output == redact(source, salt="salt")
    assert output != redact(source, salt="other")
    reply = output.body["replies"][0]
    assert len(str(reply["mid"])) == 6 and str(reply["mid"]) == reply["member"]["mid"]
    assert reply["member"]["uname"] == "用户A"
    assert (reply["root"], reply["parent"], reply["rpid"]) == (12, 13, 45)
    assert "@用户A" in reply["content"]["message"] and "[doge]\n" in reply["content"]["message"]
    assert (
        abs(len(reply["content"]["message"]) - len(source.body["replies"][0]["content"]["message"]))
        < 5
    )
    assert output.body["pagination_str"].startswith("REDACTED-")
    assert output.body["cursor"]["is_end"] is False
    assert output.body["cursor"]["pagination_reply"]["next_offset"].startswith("REDACTED-")
    assert reply["reply_control"]["location"].startswith("IP属地：")
    assert reply["content"]["at_name_to_mid"] == {"用户A": reply["mid"]}
    assert set(reply["content"]["jump_url"]) == {"文文文文", "BV1xx411c7mD"}
    assert output.query["oid"] == "42" and output.query["mid"] == str(reply["mid"])
    assert reply["member"]["avatar"].startswith("https://example.invalid/")
    assert "秘密" not in reply["unknown"]
    assert output.headers == {"verifytype": "risk"}


def test_redaction_removes_ip() -> None:
    source = sample()
    source.body["ip_info"] = {"ip": "198.51.100.7", "zone_ip": "198.51.100.7|中国"}
    source.body["biz_data"] = {"client_ip": "203.0.113.9"}
    source.body["login_mid"] = 3546000000000001
    source.body["login_mid_hash"] = "fe45c532"
    output = redact(source)
    assert output.body["ip_info"] == {"ip": "REDACTED-IP", "zone_ip": "REDACTED-IP"}
    assert output.body["biz_data"] == {"client_ip": "REDACTED-IP"}
    assert output.body["login_mid"] != 3546000000000001
    assert output.body["login_mid_hash"].startswith("REDACTED-")
    assert not scan(json.dumps(output.model_dump(mode="json"), ensure_ascii=False), ())


def test_redaction_keeps_tag_separators() -> None:
    source = sample()
    source.body["result"] = [{"tag": "咖啡,手冲咖啡,下午茶", "typename": "美食"}]
    item = redact(source).body["result"][0]
    assert item == {"tag": "文文,文文文文,文文文", "typename": "美食"}


def test_redaction_keeps_xhs_ids() -> None:
    note, comment, user = "6a316843000000000f01ecb3", "6a3170aa000000001e03c2d1", "5f1a" + "0" * 20
    source = Capture(
        platform="xhs",
        kind="comment/page",
        url_path="/api/sns/web/v2/comment/page",
        captured_at=1700000000000,
        query={"note_id": note},
        body={
            "data": {"comments": [{"id": comment, "note_id": note, "user_info": {"user_id": user}}]}
        },
    )
    output = redact(source)
    item = output.body["data"]["comments"][0]
    assert (item["id"], item["note_id"], output.query["note_id"]) == (comment, note, note)
    assert item["user_info"]["user_id"] != user and len(item["user_info"]["user_id"]) == 24


def test_leaks() -> None:
    for value in (
        "SESSDATA=secret",
        "bili_jct",
        "DedeUserID",
        "web_session",
        "a1=",
        "hdslb.com/bfs/face/123",
        "sns-avatar",
        "192.168.1.2",
        "2001:db8::1",
    ):
        assert scan(value), value
    assert scan("用户秘密", ("用户秘密",)) == ["blocklist"]
    assert not scan("https://example.invalid/abc")


async def test_store_export_and_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = await open_database(tmp_path)
    try:
        async with db.sessionmaker.begin() as session:
            session.add(Dataset(id=1, name="test", created_at=1))
            await session.flush()
            session.add(
                CollectionTask(
                    id=1,
                    dataset_id=1,
                    platform="bili",
                    status="done",
                    queue_key=1,
                    snapshot={},
                    progress={},
                    created_at=1,
                    updated_at=1,
                )
            )
        await RawCaptureSink(db.sessionmaker, 1).save(sample())
        async with db.sessionmaker() as session:
            rows = await list_for_task(session, 1)
            assert len(rows) == 1 and decompress(rows[0]) == sample()
            assert await get(session, rows[0].id) is not None
            assert await list_for_task(session, 2) == []
            root = tmp_path / "fixtures"
            path = await export_fixture(session, 1, sample().kind, "normal", trim=1, root=root)
            assert json.loads(path.read_text())["meta"]["source"] == "recorded"
            with pytest.raises(FileExistsError):
                await export_fixture(session, 1, sample().kind, "normal", root=root)

        def not_ready(platform: str) -> Any:
            def parse(capture: Capture) -> ParsedCapture | None:
                raise NotImplementedError(platform)

            return parse

        monkeypatch.setattr("gleanery.fixtures.update.parser_for", not_ready)
        assert update(root) == 1
        monkeypatch.setattr(
            "gleanery.fixtures.update.parser_for",
            lambda platform: lambda capture: ParsedCapture(report=ParseReport(items=1)),
        )
        assert update(root) == 0
        assert json.loads(path.with_suffix(".expected.json").read_text())["report"]["items"] == 1
        monkeypatch.setenv("GLEANERY_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(
            "gleanery.platforms.registry.parser_for",
            lambda platform: lambda capture: ParsedCapture(report=ParseReport(items=3)),
        )
        saved: list[ParsedCapture] = []
        monkeypatch.setattr("gleanery.cli._save_reparsed", saved.extend)
        await _run_command(argparse.Namespace(command="reparse", task=1))
        assert len(saved) == 1 and saved[0].report.items == 3
        assert "尚未写入内容库" in capsys.readouterr().out
    finally:
        await db.close()
