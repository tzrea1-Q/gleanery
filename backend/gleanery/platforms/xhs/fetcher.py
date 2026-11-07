"""小红书取数器：驱动 + 解析器 + 风控判定，实现 `Fetcher`。

驱动只产出截获，风控在驱动里逐条判定；这里把截获解析成内容和评论，并按采集深度截到上限。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from gleanery.browser.manager import BrowserManager
from gleanery.clock import SystemClock
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
    TimeRange,
)
from gleanery.platforms.xhs import selectors
from gleanery.platforms.xhs.driver import XhsDriver
from gleanery.platforms.xhs.parser import parse

logger = logging.getLogger(__name__)

LOGIN_SIGNALS = frozenset({"ssr_not_login", "user_me_guest"})
"""探活时这两种是"没登录"，不是风控。"""
ROUTE_CARD = "结果页卡片"
MAX_RETURNS = 2
"""每次搜索最多回几次结果页。回去也是一次导航，总定位不到时不能每条都多开一页。"""


@dataclass(eq=False)
class _Results:
    """一次搜索的条件，回结果页时照此重开。"""

    keyword: str
    sort: SortOrder
    time_range: TimeRange | None
    pages: int = 0
    returns: int = 0


def assemble(ref: ContentRef, depth: Depth, captures: Sequence[Capture]) -> CollectResult:
    """把打开一次笔记得到的截获拼成一条内容的采集结果。

    展开二级评论会顺带加载下一页一级评论，所以一级评论按截获顺序截到 `depth.comments`；
    二级评论合并一级评论里内嵌的和点"展开"拿到的，每条一级评论最多 `sub_comments_per_root` 条。
    """
    report = ParseReport()
    content = None
    roots: list[CommentRecord] = []
    children: dict[str, list[CommentRecord]] = {}
    seen: set[str] = set()
    for capture in captures:
        parsed = parse(capture)
        if parsed is None or capture.kind == selectors.SEARCH:
            continue
        report = report.merge(parsed.report)
        if parsed.content is not None and capture.kind in (selectors.FEED, selectors.SSR_NOTE):
            content = parsed.content
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
        raise PageChanged("missing_detail", ref.platform_id)
    # 只按链接采、没经过搜索的笔记，token 只在引用里；存进内容库，下次打开还要用。
    tokens = {key: ref.ext[key] for key in ("xsec_token", "xsec_source") if ref.ext.get(key)}
    content = content.model_copy(update={"ext": {**content.ext, **tokens}})
    kept = roots[: depth.comments]
    comments = list(kept)
    if depth.sub_comments:
        for root in kept:
            comments.extend(children.get(root.platform_id, [])[: depth.sub_comments_per_root])
    return CollectResult(content=content, comments=comments, subtitles=[], report=report)


class XhsFetcher:
    platform: Platform = "xhs"

    def __init__(self, manager: BrowserManager) -> None:
        self.manager = manager
        self._stack = AsyncExitStack()
        self._page: Any = None
        self._sources: dict[str, _Results] = {}
        """这个取数器搜到过的笔记来自哪次搜索。"""
        self._showing: _Results | None = None
        """页面当前停在哪次搜索的结果页上。"""

    async def _open(self) -> Any:
        if self._page is None:
            self._page = await self._stack.enter_async_context(self.manager.page("xhs"))
        return self._page

    async def probe(self, ctx: FetchContext) -> ProbeResult:
        driver = XhsDriver(await self._open(), ctx)
        try:
            await driver.open_home()
        except RiskDetected as error:
            if error.verdict.signal not in LOGIN_SIGNALS:
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
        # 页面的发布时间筛选只是少翻无用的页；卡片上的时间是近似的，执行器照旧采后过滤，
        # 拿到详情后再复核一次。
        driver = XhsDriver(await self._open(), ctx)
        results = self._showing = _Results(keyword, sort, time_range)
        try:
            async for capture in driver.search_pages(
                keyword, sort, time_range, SystemClock().now_ms()
            ):
                parsed = parse(capture)
                if parsed is None or parsed.search is None:
                    raise PageChanged("unparsed_search", capture.kind)
                results.pages += 1
                for record in parsed.search.contents:
                    self._sources[record.platform_id] = results
                yield parsed.search
        finally:
            await driver.close()

    async def _locate_card(self, driver: XhsDriver, note_id: str) -> str | None:
        """让页面停在这条笔记所在的结果页上并找到卡片；做不到时返回原因，改为直接打开。"""
        results = self._sources.get(note_id)
        if results is None:
            return "不是本次搜索的结果"
        if results is not self._showing:
            if results.returns >= MAX_RETURNS:
                return "回结果页的次数已用完"
            results.returns += 1
            try:
                await driver.reopen_results(results.keyword, results.sort, results.time_range)
            except PageChanged:
                return "结果页打不开"
            self._showing = results
        if await driver.find_card(note_id, results.pages):
            return None
        return "结果页里定位不到卡片"

    async def collect_content(
        self, ref: ContentRef, depth: Depth, ctx: FetchContext
    ) -> CollectResult:
        recorder = Recorder(ctx)
        driver = XhsDriver(await self._open(), recorder)
        try:
            reason = await self._locate_card(driver, ref.platform_id)
            if reason is not None:
                self._showing = None
                # 任务日志只留最近一条，直开的原因在本地日志里留底。
                logger.warning("小红书笔记 %s 直接打开：%s", ref.platform_id, reason)
            await driver.open_note(ref, depth, from_card=reason is None)
            await driver.close_note()
        finally:
            await driver.close()
        route = ROUTE_CARD if reason is None else f"直接打开：{reason}"
        return assemble(ref, depth, recorder.captures).model_copy(update={"route": route})

    async def close(self) -> None:
        self._page = self._showing = None
        self._sources.clear()
        await self._stack.aclose()
