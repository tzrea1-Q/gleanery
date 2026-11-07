"""数据集导出。"""

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.deps import get_deps, get_session
from gleanery.api.errors import ApiError, ErrorBody
from gleanery.api.schemas_data import ExportFormat, ExportOptions
from gleanery.deps import AppDeps
from gleanery.export.rows import load
from gleanery.export.writers import csv_zip, markdown, xlsx
from gleanery.query.filters import ContentFilter, ContentSort

router = APIRouter(prefix="/api/datasets", tags=["exports"])
_404: dict[int | str, dict[str, Any]] = {404: {"model": ErrorBody}}


@router.get(
    "/{dataset_id}/export",
    response_class=Response,
    responses={
        **_404,
        200: {
            "content": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
                "application/zip": {},
                "text/markdown": {},
            }
        },
    },
)
async def export_dataset(
    dataset_id: int,
    format: ExportFormat,
    session: Annotated[AsyncSession, Depends(get_session)],
    deps: Annotated[AppDeps, Depends(get_deps)],
    filter: Annotated[ContentFilter, Query()],
    options: Annotated[ExportOptions, Query()],
    sort: ContentSort = "added_desc",
) -> Response:
    data = await load(session, dataset_id, filter, sort, deps.tz)
    if data is None:
        raise ApiError(404, "DATASET_NOT_FOUND", "数据集不存在")
    now = deps.clock.now_ms()
    if format == "xlsx":
        body = await asyncio.to_thread(xlsx, data, deps.tz, now, filter, options.include_ext)
        media, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    elif format == "csv":
        body = await asyncio.to_thread(csv_zip, data, deps.tz, options.include_ext)
        media, ext = "application/zip", "zip"
    else:
        body = await asyncio.to_thread(
            markdown, data, deps.tz, now, filter, options.comment_limit, options.include_subtitles
        )
        media, ext = "text/markdown; charset=utf-8", "md"
    timestamp = datetime.fromtimestamp(now / 1000, UTC).astimezone(deps.tz).strftime("%Y%m%d-%H%M")
    filename = quote(f"{data.dataset.name}-{timestamp}.{ext}", safe="")
    return Response(
        body,
        media_type=media,
        headers={
            "Content-Disposition": f"attachment; filename=\"dataset-{dataset_id}.{ext}\"; filename*=UTF-8''{filename}"
        },
    )
