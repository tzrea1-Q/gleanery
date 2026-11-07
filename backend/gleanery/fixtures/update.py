from __future__ import annotations

import json
import sys
from pathlib import Path

from gleanery.fixtures import FIXTURES_ROOT
from gleanery.platforms.registry import parser_for
from gleanery.platforms.types import Capture


def update(root: Path = FIXTURES_ROOT) -> int:
    fixtures = sorted(
        path for path in root.rglob("*.json") if not path.name.endswith(".expected.json")
    )
    snapshots: list[tuple[Path, str]] = []
    for path in fixtures:
        capture = Capture.model_validate(json.loads(path.read_text(encoding="utf-8"))["capture"])
        try:
            parsed = parser_for(capture.platform)(capture)
        except NotImplementedError as exc:
            print(f"无法更新 {path}：解析器尚未实现（{exc}）", file=sys.stderr)
            return 1
        output = parsed.model_dump(mode="json", by_alias=True) if parsed is not None else None
        snapshots.append(
            (
                path.with_suffix(".expected.json"),
                json.dumps(output, ensure_ascii=False, indent=2) + "\n",
            )
        )
    for path, content in snapshots:
        path.write_text(content, encoding="utf-8")
    print(f"已更新 {len(snapshots)} 个 fixture 期望快照；请人工审阅差异。")
    return 0


if __name__ == "__main__":
    raise SystemExit(update())
