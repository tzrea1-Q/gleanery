"""每轮注入当前报告和用户修改。"""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.store.models import Report, ReportRevision, Setting
from gleanery.store.repo_settings import get_setting, set_setting

OPEN_REPORT_KEY = "workspace.open_report.{conversation_id}"


async def report_context(session: AsyncSession, conversation_id: int) -> str | None:
    """返回报告说明并更新快照，由调用方提交。"""
    open_key = OPEN_REPORT_KEY.format(conversation_id=conversation_id)
    open_id = await get_setting(session, open_key)
    opened = await session.get(Report, open_id) if open_id is not None else None
    if open_id is not None and opened is None:
        row = await session.get(Setting, open_key)
        if row is not None:
            await session.delete(row)
        open_id = None
    key = f"agent.injected_reports.{conversation_id}"
    seen = await get_setting(session, key, {}) or {}
    reports = (
        await session.scalars(
            select(Report)
            .where(or_(Report.created_in_conversation_id == conversation_id, Report.id == open_id))
            .order_by(Report.id)
        )
    ).all()
    lines = []
    # 注入不进消息历史，打开的报告每轮都要说，否则之后几轮模型就不知道用户在看哪份。
    if opened is not None:
        lines.append(
            f"工作区当前打开的报告：report_id={opened.id}「{opened.title}」，第 {opened.version} 版"
        )
    for report in reports:
        user_change = await session.scalar(
            select(ReportRevision.id)
            .where(
                ReportRevision.report_id == report.id,
                ReportRevision.source == "user",
                ReportRevision.version > seen.get(str(report.id), 0),
            )
            .limit(1)
        )
        if user_change is not None:
            lines.append(
                f"用户在你上次之后改过报告 report_id={report.id}「{report.title}」，现在是第 {report.version} 版；再修改前先用 get_report 取最新全文"
            )
    current = {str(report.id): report.version for report in reports}
    if current != seen:
        await set_setting(session, key, current)
    return "\n".join(["系统注入（不是用户说的话）：", *lines]) if lines else None
