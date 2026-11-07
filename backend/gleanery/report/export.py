"""将已保存的报告渲染为 Markdown。"""

from datetime import tzinfo

from gleanery.api.schemas_reports import CitationOut, ReportDetail
from gleanery.query.timefmt import local_datetime, local_iso, local_text
from gleanery.report.citations import CitationRef, to_footnotes


def render_markdown(
    report: ReportDetail, citations: list[CitationOut], now: int, tz: tzinfo | None
) -> str:
    notes = {}
    for citation in citations:
        parts = [
            {"bili": "B 站", "xhs": "小红书"}.get(citation.platform, citation.platform),
            citation.excerpt,
        ]
        if citation.author:
            parts.append(citation.author)
        parts.append(citation.url)
        # 标记放在链接后、用分隔符隔开：紧贴网址的全角括号会被自动链接吞进 URL。
        if citation.deleted:
            parts.append("已从内容库删除")
        notes[CitationRef(citation.kind, citation.target_id)] = " · ".join(parts)
    basis = report.basis
    description = (
        f"基于 {basis.contents} 条内容、{basis.comments} 条评论 · 数据集「{basis.dataset_name}」"
        if basis and report.dataset_id is not None
        else "未关联数据集"
    )
    body = report.markdown
    heading = f"# {report.title}"
    if body.splitlines() and body.splitlines()[0].strip() == heading:
        body = "\n".join(body.splitlines()[1:]).lstrip("\n")
    exported = local_iso(now, tz) or local_datetime(now, tz).isoformat(timespec="minutes")
    return (
        f"{heading}\n\n> {description} · 报告第 {report.version} 版，"
        f"更新于 {local_text(report.updated_at, tz)}\n> 导出于 {exported}\n\n"
        f"{to_footnotes(body, notes)}\n"
    )
