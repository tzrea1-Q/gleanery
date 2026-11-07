import json
from pathlib import Path

from gleanery.openapi import build_schema


def test_committed_openapi_is_current() -> None:
    """`backend/openapi.json` 与代码一致；不一致时跑 `just gen-api`。"""
    committed = json.loads((Path(__file__).parent.parent / "openapi.json").read_text("utf-8"))
    assert committed == json.loads(json.dumps(build_schema()))
