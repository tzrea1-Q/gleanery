import json
from pathlib import Path

import pytest

from gleanery.platforms.bili.risk import judge
from gleanery.platforms.types import Capture

FIXTURES = sorted(
    path
    for path in (Path(__file__).parents[2] / "fixtures" / "bili").rglob("*.json")
    if not path.name.endswith(".expected.json")
)


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_fixture_verdict(path: Path) -> None:
    data = json.loads(path.read_text())
    verdict = judge(Capture.model_validate(data["capture"]))
    case = data["meta"]["case"]
    if case.startswith("risk"):
        assert verdict is not None and verdict.kind == "risk"
    elif case == "login_lost":
        assert verdict is not None and verdict.kind == "login_required"
    else:
        assert verdict is None


def test_every_kind_has_fixtures() -> None:
    assert len({path.parent.name for path in FIXTURES}) == 7
