from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.fixtures import FIXTURES_ROOT
from gleanery.fixtures.leak import load_blocklist, scan
from gleanery.fixtures.redact import redact
from gleanery.store.repo_raw_capture import decompress, list_for_task


async def export_fixture(
    session: AsyncSession,
    task_id: int,
    kind: str,
    case: str,
    index: int = 0,
    trim: int | None = None,
    root: Path = FIXTURES_ROOT,
) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", case):
        raise ValueError("用例名称只能包含字母、数字、连字符和下划线")
    if index < 0 or (trim is not None and trim < 0):
        raise ValueError("index 和 trim 必须是非负数")
    rows = [row for row in await list_for_task(session, task_id) if row.kind == kind]
    if index >= len(rows):
        raise ValueError(f"没有匹配的原始响应：{kind}，index={index}")
    capture = redact(decompress(rows[index]), trim=trim)
    kind_dir = capture.kind.replace("/", "__").replace(":", "__")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", kind_dir):
        raise ValueError("原始响应类型不适合作为目录名")
    date = datetime.fromtimestamp(capture.captured_at / 1000, UTC)
    meta = {
        "platform": capture.platform,
        "kind": capture.kind,
        "url_path": capture.url_path,
        "captured_on": date.date().isoformat(),
        "source": "recorded",
        "case": case,
        "note": "",
    }
    content = (
        json.dumps(
            {"meta": meta, "capture": capture.model_dump(mode="json")}, ensure_ascii=False, indent=2
        )
        + "\n"
    )
    import os

    findings = scan(content, load_blocklist(os.environ.get("GLEANERY_LEAK_BLOCKLIST")))
    if findings:
        raise ValueError("脱敏后仍发现泄漏风险：" + ", ".join(findings))
    path = root / capture.platform / kind_dir / f"{date:%Y%m%d}-{case}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        file.write(content)
    return path
