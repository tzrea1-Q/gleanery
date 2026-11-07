"""导出工具。"""

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from pydantic_ai import RunContext

from gleanery.agent.deps import AgentDeps
from gleanery.api.schemas_data import ExportFormat
from gleanery.export.rows import load
from gleanery.query.filters import ContentFilter


async def export_dataset(
    ctx: RunContext[AgentDeps],
    dataset_id: int,
    format: ExportFormat,
    filter: ContentFilter | None = None,
    include_ext: bool = False,
    comment_limit: int = 20,
    include_subtitles: bool = False,
) -> dict[str, Any]:
    """导出数据集为 xlsx、csv（zip）或 md，返回下载链接，界面会显示下载卡片。"""
    if not 0 <= comment_limit <= 200:
        return {
            "error": {
                "code": "INVALID_REQUEST",
                "message": "评论条数须在 0 到 200 之间",
                "hint": None,
            }
        }
    async with ctx.deps.sessionmaker() as session:
        data = await load(session, dataset_id, filter, "added_desc", ctx.deps.tz)
    if data is None:
        return {"error": {"code": "DATASET_NOT_FOUND", "message": "数据集不存在", "hint": None}}
    ext = "zip" if format == "csv" else format
    timestamp = (
        datetime.fromtimestamp(ctx.deps.clock.now_ms() / 1000, UTC)
        .astimezone(ctx.deps.tz)
        .strftime("%Y%m%d-%H%M")
    )
    params = {
        "format": format,
        "include_ext": str(include_ext).lower(),
        "comment_limit": str(comment_limit),
        "include_subtitles": str(include_subtitles).lower(),
    }
    if filter:
        params.update(
            {
                k: str(v).lower() if isinstance(v, bool) else str(v)
                for k, v in filter.model_dump(mode="json", exclude_none=True).items()
                if v != ""
            }
        )
    return {
        "dataset_id": dataset_id,
        "format": format,
        "filename": f"{data.dataset.name}-{timestamp}.{ext}",
        "download_url": f"/api/datasets/{dataset_id}/export?{urlencode(params)}",
        "contents": len(data.contents),
        "comments": len(data.comments),
        "subtitles": len(data.subtitles),
    }
