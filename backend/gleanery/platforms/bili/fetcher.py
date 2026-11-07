"""B 站取数器：驱动 + 解析器 + 风控判定，实现 `Fetcher`。

驱动只产出截获，风控在驱动里逐条判定；这里把截获解析成内容、评论、字幕，并按采集深度截到上限。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack
from typing import Any

from gleanery.browser.manager import BrowserManager
from gleanery.platforms.bili.driver import BiliDriver
from gleanery.platforms.bili.parser import parse
from gleanery.platforms.errors import PageChanged, RiskDetected
from gleanery.platforms.recorder import Recorder
from gleanery.platforms.types import (
    Capture,
    CollectResult,
    CommentRecord,
    ContentRef,
    Depth,
    FetchContext,
    ParseReport,
    Platform,
    ProbeResult,
    SearchPage,
    SortOrder,
    SubtitleRecord,
    TimeRange,
)


def assemble(ref: ContentRef, depth: Depth, captures: Sequence[Capture]) -> CollectResult:
    """把打开一次视频页得到的截获拼成一条内容的采集结果。

    展开楼中楼会滚动页面，评论区常顺带加载下一页（2026-11-01 实测），所以一级评论按截获顺序
    截到 `depth.comments`，楼中楼只留保住的根评论下的、每楼最多 `sub_comments_per_root` 条。
    """
    report = ParseReport()
    content = None
    roots: list[CommentRecord] = []
    children: dict[str, list[CommentRecord]] = {}
    seen: set[str] = set()
    subtitles: list[SubtitleRecord] = []
    for capture in captures:
        parsed = parse(capture)
        if parsed is None:
            continue
        report = report.merge(parsed.report)
        if parsed.content is not None and capture.kind == "ssr:video":
            content = parsed.content
        subtitles.extend(parsed.subtitles)
        for comment in parsed.comments.comments if parsed.comments else []:
            if comment.platform_id in seen:
                continue
            seen.add(comment.platform_id)
            comment = comment.model_copy(update={"content_platform_id": ref.platform_id})
            if comment.root_platform_id is None:
                roots.append(comment)
            else:
                children.setdefault(comment.root_platform_id, []).append(comment)
    if content is None:
        raise PageChanged("missing_ssr", "ssr:video")
    kept = roots[: depth.comments]
    comments = list(kept)
    if depth.sub_comments:
        for root in kept:
            comments.extend(children.get(root.platform_id, [])[: depth.sub_comments_per_root])
    return CollectResult(
        content=content,
        comments=comments,
        subtitles=subtitles if depth.subtitles else [],
        report=report,
    )


class BiliFetcher:
    platform: Platform = "bili"

    def __init__(self, manager: BrowserManager) -> None:
        self.manager = manager
        self._stack = AsyncExitStack()
        self._page: Any = None

    async def _open(self) -> Any:
        if self._page is None:
            self._page = await self._stack.enter_async_context(self.manager.page("bili"))
        return self._page

    async def probe(self, ctx: FetchContext) -> ProbeResult:
        driver = BiliDriver(await self._open(), ctx)
        try:
            await driver.open_home()
        except RiskDetected as error:
            if error.verdict.kind != "login_required":
                raise
            return ProbeResult(logged_in=False, detail=error.verdict.signal)
        finally:
            await driver.close()
        return ProbeResult(logged_in=True)

    async def search(
        self,
        keyword: str,
        sort: SortOrder,
        time_range: TimeRange | None,
        ctx: FetchContext,
    ) -> AsyncIterator[SearchPage]:
        # 搜索页的发布时间筛选只是少翻无用的页；综合排序下仍会混进范围外的结果（2026-11-02 实测），
        # 所以执行器照旧按发布时间采后过滤。
        driver = BiliDriver(await self._open(), ctx)
        try:
            async for capture in driver.search_pages(keyword, sort, time_range):
                parsed = parse(capture)
                if parsed is None or parsed.search is None:
                    raise PageChanged("unparsed_search", capture.kind)
                yield parsed.search
        finally:
            await driver.close()

    async def collect_content(
        self, ref: ContentRef, depth: Depth, ctx: FetchContext
    ) -> CollectResult:
        recorder = Recorder(ctx)
        driver = BiliDriver(await self._open(), recorder)
        try:
            await driver.open_video(ref, depth)
        finally:
            await driver.close()
        return assemble(ref, depth, recorder.captures)

    async def close(self) -> None:
        self._page = None
        await self._stack.aclose()
