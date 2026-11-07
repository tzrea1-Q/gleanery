"""报告。"""

import re
from typing import Annotated, Any, cast
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.deps import get_deps, get_events, get_session
from gleanery.api.errors import ApiError, ErrorBody
from gleanery.api.schemas_reports import (
    CitationKind,
    CitationOut,
    ReportBasis,
    ReportDetail,
    ReportPage,
    ReportRestore,
    ReportRevisionDetail,
    ReportRevisionSummary,
    ReportSave,
    ReportSource,
    ReportSummary,
)
from gleanery.deps import AppDeps
from gleanery.events import EventBus
from gleanery.platforms.links import open_url
from gleanery.platforms.types import Platform
from gleanery.query.timefmt import local_datetime
from gleanery.report import repo
from gleanery.report.export import render_markdown
from gleanery.store.models import (
    Comment,
    Content,
    Conversation,
    Dataset,
    Report,
    ReportCitation,
    ReportRevision,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])
_404: dict[int | str, dict[str, Any]] = {404: {"model": ErrorBody}}
_409: dict[int | str, dict[str, Any]] = {404: {"model": ErrorBody}, 409: {"model": ErrorBody}}


async def _report(session: AsyncSession, report_id: int) -> Report:
    report = await repo.get(session, report_id)
    if report is None:
        raise ApiError(404, "REPORT_NOT_FOUND", "报告不存在")
    return report


async def _revision(session: AsyncSession, report_id: int, revision_id: int) -> ReportRevision:
    await _report(session, report_id)
    item = await repo.revision(session, report_id, revision_id)
    if item is None:
        raise ApiError(404, "REVISION_NOT_FOUND", "修订不存在")
    return item


async def _summary(session: AsyncSession, report: Report) -> ReportSummary:
    dataset = (
        await session.get(Dataset, report.dataset_id) if report.dataset_id is not None else None
    )
    conversation = (
        await session.get(Conversation, report.created_in_conversation_id)
        if report.created_in_conversation_id is not None
        else None
    )
    return ReportSummary(
        id=report.id,
        title=report.title,
        version=report.version,
        dataset_id=report.dataset_id,
        dataset_name=dataset.name if dataset else None,
        created_in_conversation_id=report.created_in_conversation_id,
        conversation_title=conversation.title if conversation else None,
        created_at=report.created_at,
        updated_at=report.updated_at,
        updated_by=cast(ReportSource, report.updated_by),
    )


async def _detail(session: AsyncSession, report: Report) -> ReportDetail:
    snapshots = (
        await session.scalars(
            select(ReportCitation)
            .where(ReportCitation.report_id == report.id)
            .order_by(ReportCitation.id)
        )
    ).all()
    citations = []
    for item in snapshots:
        deleted = (
            await session.get(Content if item.kind == "content" else Comment, item.target_id)
            is None
        )
        # 快照存的是 Agent 读到的网址；给用户点开的按内容现有的 token 补上，内容删了就没有了。
        content = await session.get(Content, item.content_id)
        citations.append(
            CitationOut(
                kind=cast(CitationKind, item.kind),
                target_id=item.target_id,
                content_id=item.content_id,
                platform=cast(Platform, item.platform),
                excerpt=item.excerpt,
                author=item.author,
                url=(
                    open_url(cast(Platform, item.platform), item.url, content.ext)
                    if content
                    else item.url
                ),
                saved_at=item.saved_at,
                deleted=deleted,
            )
        )
    return ReportDetail(
        **(await _summary(session, report)).model_dump(),
        markdown=report.markdown,
        basis=ReportBasis.model_validate(report.basis) if report.basis is not None else None,
        new_since=await repo.new_since(session, report),
        citations=citations,
    )


def _revision_summary(item: ReportRevision) -> ReportRevisionSummary:
    return ReportRevisionSummary(
        id=item.id,
        version=item.version,
        title=item.title,
        source=cast(ReportSource, item.source),
        conversation_id=item.conversation_id,
        created_at=item.created_at,
    )


async def _write(
    session: AsyncSession,
    report_id: int,
    base_version: int,
    title: str,
    markdown: str,
    conversation_id: int | None,
    deps: AppDeps,
    events: EventBus,
) -> ReportDetail:
    try:
        report = await repo.update(
            session,
            report_id,
            base_version=base_version,
            title=title,
            markdown=markdown,
            source="user",
            conversation_id=conversation_id,
            now=deps.clock.now_ms(),
        )
    except LookupError as exc:
        raise ApiError(404, "REPORT_NOT_FOUND", "报告不存在") from exc
    except repo.VersionConflict as exc:
        raise ApiError(409, "VERSION_CONFLICT", "报告已被修改，请重新加载") from exc
    result = await _detail(session, report)
    await session.commit()
    events.publish(
        "report.updated", {"report_id": report.id, "version": report.version, "source": "user"}
    )
    return result


@router.get("", response_model=ReportPage)
async def list_reports(
    session: Annotated[AsyncSession, Depends(get_session)],
    keyword: str | None = None,
    dataset_id: int | None = None,
    conversation_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ReportPage:
    items, total = await repo.list_reports(
        session,
        keyword=keyword,
        dataset_id=dataset_id,
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
    )
    return ReportPage(items=[await _summary(session, item) for item in items], total=total)


@router.get("/{report_id}", response_model=ReportDetail, responses=_404)
async def get_report(
    report_id: int, session: Annotated[AsyncSession, Depends(get_session)]
) -> ReportDetail:
    return await _detail(session, await _report(session, report_id))


@router.put("/{report_id}", response_model=ReportDetail, responses=_409)
async def save_report(
    report_id: int,
    body: ReportSave,
    session: Annotated[AsyncSession, Depends(get_session)],
    deps: Annotated[AppDeps, Depends(get_deps)],
    events: Annotated[EventBus, Depends(get_events)],
    x_conversation_id: Annotated[int | None, Header()] = None,
) -> ReportDetail:
    """用户保存：不校验引用，版本冲突返回 409 `VERSION_CONFLICT`。"""
    return await _write(
        session,
        report_id,
        body.base_version,
        body.title,
        body.markdown,
        x_conversation_id,
        deps,
        events,
    )


@router.delete("/{report_id}", status_code=204, responses=_404)
async def delete_report(
    report_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    events: Annotated[EventBus, Depends(get_events)],
) -> None:
    await _report(session, report_id)
    await repo.delete(session, report_id)
    await session.commit()
    events.publish("report.deleted", {"report_id": report_id})


@router.get("/{report_id}/revisions", response_model=list[ReportRevisionSummary], responses=_404)
async def list_revisions(
    report_id: int, session: Annotated[AsyncSession, Depends(get_session)]
) -> list[ReportRevisionSummary]:
    await _report(session, report_id)
    return [_revision_summary(item) for item in await repo.revisions(session, report_id)]


@router.get(
    "/{report_id}/revisions/{revision_id}", response_model=ReportRevisionDetail, responses=_404
)
async def get_revision(
    report_id: int, revision_id: int, session: Annotated[AsyncSession, Depends(get_session)]
) -> ReportRevisionDetail:
    item = await _revision(session, report_id, revision_id)
    return ReportRevisionDetail(**_revision_summary(item).model_dump(), markdown=item.markdown)


@router.post(
    "/{report_id}/revisions/{revision_id}/restore", response_model=ReportDetail, responses=_409
)
async def restore_revision(
    report_id: int,
    revision_id: int,
    body: ReportRestore,
    session: Annotated[AsyncSession, Depends(get_session)],
    deps: Annotated[AppDeps, Depends(get_deps)],
    events: Annotated[EventBus, Depends(get_events)],
    x_conversation_id: Annotated[int | None, Header()] = None,
) -> ReportDetail:
    """把该版本的标题和正文作为一次新的用户保存。"""
    item = await _revision(session, report_id, revision_id)
    return await _write(
        session,
        report_id,
        body.base_version,
        item.title,
        item.markdown,
        x_conversation_id,
        deps,
        events,
    )


@router.get(
    "/{report_id}/export",
    response_class=Response,
    responses={**_404, 200: {"content": {"text/markdown": {}}}},
)
async def export_report(
    report_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    deps: Annotated[AppDeps, Depends(get_deps)],
) -> Response:
    """导出当前已保存的版本为 `.md`，引用转成脚注。"""
    report = await _detail(session, await _report(session, report_id))
    now = deps.clock.now_ms()
    title = re.sub(r'[\\/:*?"<>|\r\n]', "_", report.title)
    date = local_datetime(now, deps.tz).strftime("%Y%m%d")
    filename = quote(f"{title}-{date}.md", safe="")
    return Response(
        render_markdown(report, report.citations, now, deps.tz),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"report-{report_id}.md\"; filename*=UTF-8''{filename}"
        },
    )
