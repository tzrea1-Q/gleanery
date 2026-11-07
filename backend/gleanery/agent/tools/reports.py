"""报告工具。四个都不需要审批。

工具描述经真模型冒烟定稿。
"""

from typing import Any

from pydantic import BaseModel
from pydantic_ai import RunContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.agent.deps import AgentDeps
from gleanery.agent.tools import error
from gleanery.query.timefmt import local_iso
from gleanery.report import citations, repo
from gleanery.store.models import Comment, Content, Dataset, Report, ReportCitation


class ReportEdit(BaseModel):
    old_text: str
    """原文里要替换的一段，必须恰好出现一次。"""
    new_text: str


async def _validate(
    session: AsyncSession, markdown: str, report_id: int | None
) -> dict[str, Any] | None:
    malformed = citations.malformed(markdown)
    if malformed:
        return error(
            "INVALID_CITATION",
            "引用格式不正确",
            f"{', '.join(malformed)}；请写成 [[c:内容ID]] 或 [[m:评论ID]]",
        )
    if any(marker.too_many for marker in citations.parse(markdown)):
        return error("INVALID_CITATION", "单个引用最多包含 10 个 ID")
    unknown = await repo.unknown_refs(session, report_id, citations.refs(markdown))
    if unknown:
        return error("UNKNOWN_CITATION", "引用不存在", ", ".join(ref.label() for ref in unknown))
    return None


def _conflict(report: Report) -> dict[str, Any]:
    return {
        **error("VERSION_CONFLICT", "报告已被修改", "请根据最新全文重新修改"),
        "current": {"version": report.version, "title": report.title, "markdown": report.markdown},
    }


def _result(report: Report) -> dict[str, Any]:
    return {
        "report_id": report.id,
        "version": report.version,
        "title": report.title,
        "citations": len(citations.refs(report.markdown)),
        "basis": report.basis,
    }


async def save_report(
    ctx: RunContext[AgentDeps], title: str, markdown: str, dataset_id: int | None = None
) -> dict[str, Any]:
    """新建一份报告（GFM Markdown），工作区会显示它。

    本对话里已有报告时，默认用 update_report 改那一份；只有用户明确要另写一份，或主题、数据集换了，才新建。
    引用原文写 [[c:内容ID]] 或 [[m:评论ID]]，多个用逗号隔开，如 [[c:12, m:345]]，一个标记最多 10 个；
    引用只做代表性例证：计数写在正文里，再配 2–3 个引用。ID 必须来自工具结果。引用标记只在报告正文里渲染，对话回复里不要写。

    Args:
        title: 报告标题，界面单独显示。
        markdown: 报告正文，GFM Markdown，从第一节写起，不要再写一级标题。不要写原始 HTML。
        dataset_id: 主数据集 ID，界面按它显示"基于多少条内容、评论"。
    """
    if not title.strip():
        return error("INVALID_REQUEST", "标题不能为空")
    async with ctx.deps.sessionmaker() as session:
        if dataset_id is not None and await session.get(Dataset, dataset_id) is None:
            return error("DATASET_NOT_FOUND", "数据集不存在")
        invalid = await _validate(session, markdown, None)
        if invalid:
            return invalid
        report = await repo.create(
            session,
            title=title,
            markdown=markdown,
            dataset_id=dataset_id,
            conversation_id=ctx.deps.conversation_id,
            source="agent",
            now=ctx.deps.clock.now_ms(),
        )
        result = {**_result(report), "dataset_id": report.dataset_id}
        await session.commit()
    ctx.deps.events.publish(
        "report.updated",
        {"report_id": result["report_id"], "version": result["version"], "source": "agent"},
    )
    return result


async def update_report(
    ctx: RunContext[AgentDeps],
    report_id: int,
    base_version: int,
    title: str | None = None,
    markdown: str | None = None,
    edits: list[ReportEdit] | None = None,
) -> dict[str, Any]:
    """修改报告。用户追问时默认改本对话里最近的一份；改别的对话里的旧报告，先 list_reports / get_report。

    只改一两处时用 edits（精确替换，不会碰到用户改过的其他段落），大改时用 markdown 整篇替换，二者只给一个。
    返回 VERSION_CONFLICT 说明用户刚改过：结果的 current 里是最新全文和版本号，按它重做修改，不要覆盖用户的改动。

    Args:
        report_id: 报告 ID。
        base_version: 你最近读到或写入的版本号。
        title: 新标题，不改就省略。
        markdown: 整篇替换后的正文。
        edits: 依次应用的精确替换 [{old_text, new_text}]，每条的 old_text 在当时的正文里必须恰好出现一次，
            写得长一点以免重复。
    """
    if markdown is not None and edits is not None:
        return error("INVALID_REQUEST", "markdown 和 edits 只能给一个")
    if title is None and markdown is None and edits is None:
        return error("INVALID_REQUEST", "请提供要修改的内容")
    async with ctx.deps.sessionmaker() as session:
        report = await repo.get(session, report_id)
        if report is None:
            return error("REPORT_NOT_FOUND", "报告不存在")
        if report.version != base_version:
            return _conflict(report)
        if edits is not None:
            try:
                markdown = repo.apply_edits(report.markdown, [edit.model_dump() for edit in edits])
            except (repo.EditNotFound, repo.EditAmbiguous) as exc:
                hint = f"第 {exc.index + 1} 条：{exc.old_text[:40]}"
                if isinstance(exc, repo.EditAmbiguous):
                    return error(
                        "EDIT_AMBIGUOUS", "替换原文出现多次", f"{hint}；出现 {exc.count} 次"
                    )
                return error("EDIT_NOT_FOUND", "找不到替换原文", hint)
        invalid = await _validate(
            session, markdown if markdown is not None else report.markdown, report_id
        )
        if invalid:
            return invalid
        try:
            report = await repo.update(
                session,
                report_id,
                base_version=base_version,
                title=title,
                markdown=markdown,
                source="agent",
                conversation_id=ctx.deps.conversation_id,
                now=ctx.deps.clock.now_ms(),
            )
        except repo.VersionConflict as exc:
            return _conflict(exc.current)
        except LookupError:
            return error("REPORT_NOT_FOUND", "报告不存在")
        result = _result(report)
        await session.commit()
    ctx.deps.events.publish(
        "report.updated", {"report_id": report_id, "version": result["version"], "source": "agent"}
    )
    return result


async def get_report(ctx: RunContext[AgentDeps], report_id: int) -> dict[str, Any]:
    """读取报告当前全文（含用户的修改）、版本号和引用快照。"""
    async with ctx.deps.sessionmaker() as session:
        report = await repo.get(session, report_id)
        if report is None:
            return error("REPORT_NOT_FOUND", "报告不存在")
        dataset = (
            await session.get(Dataset, report.dataset_id) if report.dataset_id is not None else None
        )
        snapshots = (
            await session.scalars(
                select(ReportCitation)
                .where(ReportCitation.report_id == report_id)
                .order_by(ReportCitation.id)
            )
        ).all()
        items = []
        for item in snapshots:
            deleted = (
                await session.get(Content if item.kind == "content" else Comment, item.target_id)
                is None
            )
            items.append(
                {
                    "ref": f"{'c' if item.kind == 'content' else 'm'}:{item.target_id}",
                    "platform": item.platform,
                    "url": item.url,
                    "deleted": deleted,
                    "untrusted": {"excerpt": item.excerpt, "author": item.author},
                }
            )
        return {
            "report_id": report.id,
            "title": report.title,
            "version": report.version,
            "dataset_id": report.dataset_id,
            "dataset_name": dataset.name if dataset else None,
            "created_in_conversation_id": report.created_in_conversation_id,
            "updated_at": local_iso(report.updated_at, ctx.deps.tz),
            "updated_by": report.updated_by,
            "markdown": report.markdown,
            "citations": items,
        }


async def list_reports(
    ctx: RunContext[AgentDeps],
    keyword: str | None = None,
    dataset_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """列出报告（所有对话的都在内），按更新时间倒序；可按标题关键词、主数据集筛选。

    Args:
        keyword: 标题里包含的词。
        dataset_id: 主数据集 ID。
        limit: 每页条数，1–50。
        offset: 翻页起点。
    """
    if not 1 <= limit <= 50 or offset < 0:
        return error("INVALID_REQUEST", "limit 须为 1 至 50，offset 不能为负数")
    async with ctx.deps.sessionmaker() as session:
        reports, total = await repo.list_reports(
            session, keyword=keyword, dataset_id=dataset_id, limit=limit, offset=offset
        )
        items = []
        for report in reports:
            dataset = (
                await session.get(Dataset, report.dataset_id)
                if report.dataset_id is not None
                else None
            )
            items.append(
                {
                    "report_id": report.id,
                    "title": report.title,
                    "dataset_id": report.dataset_id,
                    "dataset_name": dataset.name if dataset else None,
                    "updated_at": local_iso(report.updated_at, ctx.deps.tz),
                    "updated_by": report.updated_by,
                    "created_in_conversation_id": report.created_in_conversation_id,
                    "this_conversation": report.created_in_conversation_id
                    == ctx.deps.conversation_id,
                }
            )
        returned = len(items)
        return {
            "items": items,
            "total": total,
            "offset": offset,
            "returned": returned,
            "next_offset": offset + returned if offset + returned < total else None,
        }
