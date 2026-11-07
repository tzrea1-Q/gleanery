import json
from pathlib import Path

import pytest

from gleanery.platforms.types import Capture
from gleanery.platforms.xhs.risk import judge

FIXTURES = sorted(
    path
    for path in (Path(__file__).parents[2] / "fixtures" / "xhs").rglob("*.json")
    if not path.name.endswith(".expected.json")
)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_fixture_verdict(path: Path) -> None:
    data = json.loads(path.read_text())
    verdict = judge(Capture.model_validate(data["capture"]))
    assert (verdict.kind if verdict else None) == data["meta"]["verdict"]
