"""平台层的公共类型。

数据流：驱动操作页面 → 产出 `Capture` → 交给 `CaptureSink` 留存原始响应 → 解析器把 `Capture`
解析成 `*Record` 与 `ParseReport` → 风控判定从 `Capture` 判断 `RiskVerdict`。执行器只经 `Fetcher`
接口与平台层交互。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

Platform = Literal["bili", "xhs"]
SortOrder = Literal["default", "hot", "new"]
"""综合 / 最热 / 最新，由驱动映射到平台页面的选项。"""

# ---------- 截获记录 ----------


class Capture(BaseModel):
    """一次截获：一条接口响应，或一段页面 SSR 状态。与 `raw_capture` 表同构。"""

    platform: Platform
    kind: str
    """接口路径尾部（如 `x/v2/reply/wbi/main`），或 SSR 片段名（如 `ssr:search`、`ssr:video`）。"""
    url_path: str
    """不含查询串的路径；SSR 片段为页面路径。"""
    query: dict[str, str] = Field(default_factory=dict)
    """查询串，去掉签名参数（`w_rid`、`wts`）后的部分。"""
    status: int = 200
    headers: dict[str, str] = Field(default_factory=dict)
    """只留风控判定要用的白名单响应头（键小写）。"""
    body: Any
    """JSON 正文；接口返回非 JSON（如 412 拦截页）时为截短的文本。"""
    captured_at: int


class CaptureSink(Protocol):
    """原始响应留存。

    驱动每截获一条要用的响应就交给它；不交 `nav`、`user/me` 这类带本人账号信息的响应。
    """

    async def save(self, capture: Capture) -> None: ...


# ---------- 解析产出 ----------

ContentKind = Literal["image_text", "video"]
Completeness = Literal["summary", "detail"]


class AuthorRecord(BaseModel):
    platform: Platform
    platform_id: str
    nickname: str | None = None
    avatar_url: str | None = None
    ext: dict[str, Any] = Field(default_factory=dict)


class Counts(BaseModel):
    """互动数，已规范化为整数；解析不了的为 None（不当 0）。原文进 `ext.counts_raw`。"""

    likes: int | None = None
    favorites: int | None = None
    comments: int | None = None
    shares: int | None = None
    plays: int | None = None


class ContentRecord(BaseModel):
    platform: Platform
    platform_id: str
    url: str
    kind: ContentKind
    title: str | None = None
    body: str | None = None
    author: AuthorRecord | None = None
    published_at: int | None = None
    platform_updated_at: int | None = None
    counts: Counts = Field(default_factory=Counts)
    tags: list[str] = Field(default_factory=list)
    completeness: Completeness
    ext: dict[str, Any] = Field(default_factory=dict)
    """平台特有字段；B 站有 `aid`、`cid`、`coins`、`danmaku`、`counts_raw`、`counts_approx` 等。"""


class CommentRecord(BaseModel):
    platform: Platform
    platform_id: str
    content_platform_id: str
    root_platform_id: str | None = None
    parent_platform_id: str | None = None
    author: AuthorRecord | None = None
    body: str
    published_at: int | None = None
    likes: int | None = None
    reply_count: int | None = None
    ip_location: str | None = None
    ext: dict[str, Any] = Field(default_factory=dict)


class SubtitleSegment(BaseModel):
    start: float = Field(alias="from")
    end: float = Field(alias="to")
    content: str

    model_config = {"populate_by_name": True}


class SubtitleRecord(BaseModel):
    content_platform_id: str
    part_id: str
    part_title: str | None = None
    lang: str
    ai_generated: bool
    segments: list[SubtitleSegment]

    @property
    def text(self) -> str:
        return "\n".join(segment.content for segment in self.segments)


class ParseReport(BaseModel):
    """一次解析的统计，执行器按任务汇总，用于判定页面改版。"""

    items: int = 0
    """解析出的条目数（内容或评论）。"""
    skipped_missing_core: int = 0
    """缺核心字段被跳过的条数：缺平台内 ID，或标题与正文都缺。"""
    missing_fields: dict[str, int] = Field(default_factory=dict)
    """次要字段缺失或解析不了的计数，如 `{"likes": 2}`。"""
    nonempty_response: bool = False
    """响应本身不为空（有数据结构）。为 True 而 items == 0 时是页面改版信号。"""

    def merge(self, other: ParseReport) -> ParseReport:
        fields = dict(self.missing_fields)
        for key, value in other.missing_fields.items():
            fields[key] = fields.get(key, 0) + value
        return ParseReport(
            items=self.items + other.items,
            skipped_missing_core=self.skipped_missing_core + other.skipped_missing_core,
            missing_fields=fields,
            nonempty_response=self.nonempty_response or other.nonempty_response,
        )


class SearchPage(BaseModel):
    contents: list[ContentRecord]
    """本页的内容，完整度为 summary。"""
    has_more: bool
    report: ParseReport


class CommentPage(BaseModel):
    comments: list[CommentRecord]
    has_more: bool
    report: ParseReport


# ---------- 风控判定 ----------

RiskKind = Literal["risk", "login_required", "risk_and_login"]
"""`risk`：风控，冷却或锁定；`login_required`：登录态失效（B 站）；`risk_and_login`：小红书
`guest=true` 或 -100，按风控处理同时转为需要登录。"""


class RiskVerdict(BaseModel):
    kind: RiskKind
    signal: str
    """如 `http_412`、`code_-352`、`v_voucher`、`nav_not_login`、`code_-101`。"""
    signal_type: Literal["status", "code", "login_lost", "page"]
    detail: str | None = None


# ---------- 执行器调用的接口 ----------


class ContentRef(BaseModel):
    """打开一条内容页所需的引用。由解析器或链接解析产出，Agent 不接触。"""

    platform: Platform
    platform_id: str
    url: str
    ext: dict[str, Any] = Field(default_factory=dict)
    """如小红书的 `xsec_token` / `xsec_source`。"""


class Depth(BaseModel):
    """采集深度。评论、二级评论、字幕任一打开时隐含打开详情。"""

    model_config = ConfigDict(use_attribute_docstrings=True)

    detail: bool = True
    """是否打开内容页取详情。"""
    comments: int = 0
    """每条内容最多几条一级评论，0 为不要。"""
    sub_comments: bool = False
    """是否要二级评论（B 站叫楼中楼）。"""
    sub_comments_per_root: int = 0
    """每条一级评论最多几条二级评论。"""
    subtitles: bool = False
    """是否要字幕，仅 B 站。"""

    @property
    def opens_page(self) -> bool:
        return self.detail or self.comments > 0 or self.sub_comments or self.subtitles


class TimeRange(BaseModel):
    """近 N 天，或起止日期（本地日期，含两端）。含义是"结果保证落在范围内"。"""

    model_config = ConfigDict(use_attribute_docstrings=True)

    last_days: int | None = Field(default=None, ge=1)
    """近 N 天；用起止日期时为 null。"""
    start: str | None = None
    """起始日期 YYYY-MM-DD。"""
    end: str | None = None
    """结束日期 YYYY-MM-DD。"""


class CollectResult(BaseModel):
    content: ContentRecord
    """完整度为 detail。"""
    comments: list[CommentRecord]
    subtitles: list[SubtitleRecord]
    report: ParseReport
    route: str | None = None
    """打开内容页走的路径，写进任务日志；只有一条路径的平台留空。"""


class ProbeResult(BaseModel):
    logged_in: bool
    detail: str | None = None


PaceKind = Literal["page", "comment_page"]


class Pacer(Protocol):
    """限速。驱动在每次导航、点击、滚动翻页前调用；执行器按平台限速参数和假时钟实现。"""

    async def wait(self, kind: PaceKind) -> None: ...


class FetchContext(Protocol):
    sink: CaptureSink
    pacer: Pacer

    def log(self, message: str) -> None:
        """写进任务的"最近一条日志"和本地日志；不得含 Cookie、token。"""
        ...


class Fetcher(Protocol):
    """一个平台的取数入口（ADR-0001：页面驱动）。

    出错时抛 `gleanery.platforms.errors` 里的异常，执行器据此转移任务与平台状态。
    """

    platform: Platform

    async def probe(self, ctx: FetchContext) -> ProbeResult:
        """探活：打开一次平台页面，确认登录态。空闲超过 3 天时打开首页。"""
        ...

    def search(
        self,
        keyword: str,
        sort: SortOrder,
        time_range: TimeRange | None,
        ctx: FetchContext,
    ) -> AsyncIterator[SearchPage]:
        """逐页产出搜索结果，调用方拿够了就停止迭代。时间范围页面有筛选就用，没有由执行器采后过滤。"""
        ...

    async def collect_content(
        self, ref: ContentRef, depth: Depth, ctx: FetchContext
    ) -> CollectResult:
        """打开一次内容页，在同一页里拿完详情、评论、二级评论和字幕。"""
        ...

    async def close(self) -> None: ...


class ParsedCapture(BaseModel):
    """解析器对单条截获的产出。`gleanery reparse` 与 fixture 期望快照都用它。"""

    search: SearchPage | None = None
    content: ContentRecord | None = None
    comments: CommentPage | None = None
    subtitles: list[SubtitleRecord] = Field(default_factory=list)
    report: ParseReport = Field(default_factory=ParseReport)


class Parser(Protocol):
    """每个平台的解析器入口：纯函数。认不出的截获返回 None（只记日志）。"""

    def __call__(self, capture: Capture) -> ParsedCapture | None: ...


class RiskJudge(Protocol):
    """每个平台的风控判定入口：纯函数。没有信号时返回 None。"""

    def __call__(self, capture: Capture) -> RiskVerdict | None: ...
