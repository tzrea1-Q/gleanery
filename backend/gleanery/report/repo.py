"""报告及其修订和引用快照；事务由调用方提交。"""

from collections.abc import Mapping, Sequence

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from gleanery.query.filters import like_pattern
from gleanery.report.citations import CitationRef, refs
from gleanery.store.models import (
    Author,
    Comment,
    Content,
    Dataset,
    DatasetItem,
    Report,
    ReportCitation,
    ReportRevision,
)


class VersionConflict(Exception):
    def __init__(self, current: Report) -> None:
        self.current = current
        super().__init__(str(current.version))


class EditNotFound(Exception):
    def __init__(self, index: int, old_text: str) -> None:
        self.index, self.old_text = index, old_text
        super().__init__(old_text)


class EditAmbiguous(Exception):
    def __init__(self, index: int, old_text: str, count: int) -> None:
        self.index, self.old_text, self.count = index, old_text, count
        super().__init__(old_text)


def apply_edits(markdown: str, edits: Sequence[Mapping[str, str]]) -> str:
    for index, edit in enumerate(edits):
        old = edit["old_text"]
        count = 0
        position = 0
        while old and (position := markdown.find(old, position)) != -1:
            count += 1
            position += 1
        if not count:
            raise EditNotFound(index, old)
        if count != 1:
            raise EditAmbiguous(index, old, count)
        markdown = markdown.replace(old, edit["new_text"], 1)
    return markdown


async def get(session: AsyncSession, report_id: int) -> Report | None:
    return await session.get(Report, report_id, populate_existing=True)


async def list_reports(
    session: AsyncSession,
    *,
    keyword: str | None = None,
    dataset_id: int | None = None,
    conversation_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Report], int]:
    query = select(Report)
    if keyword is not None:
        query = query.where(Report.title.like(like_pattern(keyword), escape="\\"))
    if dataset_id is not None:
        query = query.where(Report.dataset_id == dataset_id)
    if conversation_id is not None:
        query = query.where(Report.created_in_conversation_id == conversation_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = await session.scalars(
        query.order_by(Report.updated_at.desc(), Report.id.desc()).limit(limit).offset(offset)
    )
    return list(items), total


async def _save(
    session: AsyncSession, report: Report, source: str, conversation_id: int | None, now: int
) -> None:
    session.add(
        ReportRevision(
            report_id=report.id,
            version=report.version,
            title=report.title,
            markdown=report.markdown,
            source=source,
            conversation_id=conversation_id,
            created_at=now,
        )
    )
    await session.flush()
    keep = (
        select(ReportRevision.id)
        .where(ReportRevision.report_id == report.id)
        .order_by(ReportRevision.version.desc())
        .limit(50)
    )
    await session.execute(
        sql_delete(ReportRevision).where(
            ReportRevision.report_id == report.id, ReportRevision.id.not_in(keep)
        )
    )
    old = {
        (item.kind, item.target_id): item
        for item in (
            await session.scalars(
                select(ReportCitation).where(ReportCitation.report_id == report.id)
            )
        ).all()
    }
    referenced = refs(report.markdown)
    keys = {(ref.kind, ref.id) for ref in referenced}
    for key, item in old.items():
        if key not in keys:
            await session.delete(item)
    for ref in referenced:
        target = await session.get(Content if ref.kind == "content" else Comment, ref.id)
        if target is None:
            continue
        content = (
            target if isinstance(target, Content) else await session.get(Content, target.content_id)
        )
        assert content is not None
        author = (
            await session.get(Author, target.author_id) if target.author_id is not None else None
        )
        excerpt = (
            (target.title or target.body or "") if isinstance(target, Content) else target.body
        )
        excerpt = " ".join(excerpt.splitlines())
        excerpt = excerpt[:80] + "…" if len(excerpt) > 80 else excerpt
        item = old.get((ref.kind, ref.id))
        if item is None:
            item = ReportCitation(report_id=report.id, kind=ref.kind, target_id=ref.id)
            session.add(item)
        item.content_id, item.platform, item.excerpt = content.id, target.platform, excerpt
        item.author, item.url, item.saved_at = author.nickname if author else None, content.url, now
    dataset = (
        await session.get(Dataset, report.dataset_id) if report.dataset_id is not None else None
    )
    if dataset is None:
        report.basis = None
    else:
        members = select(DatasetItem.content_id).where(DatasetItem.dataset_id == dataset.id)
        contents = (
            await session.scalar(
                select(func.count())
                .select_from(DatasetItem)
                .where(DatasetItem.dataset_id == dataset.id)
            )
            or 0
        )
        comments = (
            await session.scalar(
                select(func.count()).select_from(Comment).where(Comment.content_id.in_(members))
            )
            or 0
        )
        report.basis = {
            "dataset_name": dataset.name,
            "contents": contents,
            "comments": comments,
            "recorded_at": now,
        }
    await session.flush()


async def create(
    session: AsyncSession,
    *,
    title: str,
    markdown: str,
    dataset_id: int | None,
    conversation_id: int | None,
    source: str,
    now: int,
) -> Report:
    report = Report(
        title=title,
        markdown=markdown,
        version=1,
        dataset_id=dataset_id,
        created_in_conversation_id=conversation_id,
        created_at=now,
        updated_at=now,
        updated_by=source,
    )
    session.add(report)
    await session.flush()
    await _save(session, report, source, conversation_id, now)
    return report


async def update(
    session: AsyncSession,
    report_id: int,
    *,
    base_version: int,
    title: str | None = None,
    markdown: str | None = None,
    source: str,
    conversation_id: int | None,
    now: int,
) -> Report:
    values: dict = {"version": Report.version + 1, "updated_at": now, "updated_by": source}
    if title is not None:
        values["title"] = title
    if markdown is not None:
        values["markdown"] = markdown
    result = await session.execute(
        sql_update(Report)
        .where(Report.id == report_id, Report.version == base_version)
        .values(**values)
        .returning(Report.id)
    )
    changed = result.scalar_one_or_none()
    report = await get(session, report_id)
    if report is None:
        raise LookupError(report_id)
    if changed is None:
        raise VersionConflict(report)
    await _save(session, report, source, conversation_id, now)
    return report


async def delete(session: AsyncSession, report_id: int) -> None:
    await session.execute(sql_delete(Report).where(Report.id == report_id))


async def revisions(session: AsyncSession, report_id: int) -> list[ReportRevision]:
    rows = await session.scalars(
        select(ReportRevision)
        .options(
            load_only(
                ReportRevision.id,
                ReportRevision.report_id,
                ReportRevision.version,
                ReportRevision.title,
                ReportRevision.source,
                ReportRevision.conversation_id,
                ReportRevision.created_at,
            )
        )
        .where(ReportRevision.report_id == report_id)
        .order_by(ReportRevision.version.desc())
    )
    return list(rows)


async def revision(
    session: AsyncSession, report_id: int, revision_id: int
) -> ReportRevision | None:
    return await session.scalar(
        select(ReportRevision).where(
            ReportRevision.report_id == report_id, ReportRevision.id == revision_id
        )
    )


async def unknown_refs(
    session: AsyncSession, report_id: int | None, refs: Sequence[CitationRef]
) -> list[CitationRef]:
    unknown = []
    for ref in refs:
        if await session.get(Content if ref.kind == "content" else Comment, ref.id) is not None:
            continue
        snapshot = (
            await session.scalar(
                select(ReportCitation.id).where(
                    ReportCitation.report_id == report_id,
                    ReportCitation.kind == ref.kind,
                    ReportCitation.target_id == ref.id,
                )
            )
            if report_id is not None
            else None
        )
        if snapshot is None:
            unknown.append(ref)
    return unknown


async def new_since(session: AsyncSession, report: Report) -> int | None:
    if report.dataset_id is None or report.basis is None:
        return None
    return (
        await session.scalar(
            select(func.count())
            .select_from(DatasetItem)
            .where(
                DatasetItem.dataset_id == report.dataset_id,
                DatasetItem.added_at > report.basis["recorded_at"],
            )
        )
        or 0
    )
