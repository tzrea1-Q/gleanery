"""M3 的报告 REST 模型。"""

from typing import Literal

from pydantic import BaseModel

from gleanery.platforms.types import Platform

ReportSource = Literal["agent", "user"]
CitationKind = Literal["content", "comment"]


class ReportBasis(BaseModel):
    """依据：保存时由应用记下，不由 Agent 写。"""

    dataset_name: str
    contents: int
    comments: int
    """主数据集内容的本地评论数，含回复。"""
    recorded_at: int


class ReportSummary(BaseModel):
    id: int
    title: str
    version: int
    dataset_id: int | None
    dataset_name: str | None
    created_in_conversation_id: int | None
    conversation_title: str | None
    created_at: int
    updated_at: int
    updated_by: ReportSource


class ReportPage(BaseModel):
    items: list[ReportSummary]
    total: int


class CitationOut(BaseModel):
    kind: CitationKind
    target_id: int
    content_id: int
    """引评论时为所属内容的内部 ID；引内容时等于 target_id。"""
    platform: Platform
    excerpt: str
    author: str | None
    url: str
    saved_at: int
    deleted: bool
    """内容库里已没有它，只剩快照。"""


class ReportDetail(ReportSummary):
    markdown: str
    basis: ReportBasis | None
    new_since: int | None
    """主数据集自本报告最后保存以来新增的条数；没有主数据集时为 None。"""
    citations: list[CitationOut]


class ReportSave(BaseModel):
    base_version: int
    title: str
    markdown: str


class ReportRestore(BaseModel):
    base_version: int


class ReportRevisionSummary(BaseModel):
    id: int
    version: int
    title: str
    source: ReportSource
    conversation_id: int | None
    created_at: int


class ReportRevisionDetail(ReportRevisionSummary):
    markdown: str


class WorkspaceState(BaseModel):
    """工作区里当前打开的报告，供每轮注入用。"""

    report_id: int | None
