"""小红书驱动：操作页面、产出截获。

页面自己加签发请求，驱动只读响应和页面状态（ADR-0001）。每截获一条都先过风控判定。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import suppress
from typing import Any, Protocol
from urllib.parse import parse_qsl, quote, urlsplit

from playwright.async_api import TimeoutError as PlaywrightTimeout

from gleanery.clock import SystemClock
from gleanery.platforms.errors import PageChanged, RiskDetected, TransientError
from gleanery.platforms.navigation import goto
from gleanery.platforms.scroll import scroll_until
from gleanery.platforms.types import (
    Capture,
    ContentRef,
    Depth,
    FetchContext,
    SortOrder,
    TimeRange,
)
from gleanery.platforms.xhs import selectors
from gleanery.platforms.xhs.links import with_token
from gleanery.platforms.xhs.risk import judge
from gleanery.platforms.xhs.timefilter import filter_option


class Page(Protocol):
    url: str
    context: Any
    main_frame: Any
    mouse: Any
    keyboard: Any

    def on(self, event: str, callback: Callable[..., None]) -> Any: ...
    def remove_listener(self, event: str, callback: Callable[..., None]) -> Any: ...
    async def goto(self, url: str, *, wait_until: str) -> Any: ...
    async def evaluate(self, expression: str, arg: Any = None) -> Any: ...
    def locator(self, selector: str) -> Any: ...


def _data(capture: Capture) -> dict[str, Any]:
    body = capture.body
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, dict) else {}


class XhsDriver:
    def __init__(self, page: Page, ctx: FetchContext) -> None:
        self.page, self.ctx = page, ctx
        self._tasks: list[asyncio.Task[None]] = []
        self.captures: list[Capture] = []
        self._event = asyncio.Event()
        self._failure: BaseException | None = None
        self._lock = asyncio.Lock()
        self.modal = False
        """当前笔记是从搜索结果点开的弹层，看完要关掉回到结果页。"""
        self.page.on("response", self._on_response)
        self.page.on("framenavigated", self._on_navigated)

    # ---------- 截获 ----------

    def _spawn(self, capture: Any) -> None:
        self._tasks.append(asyncio.create_task(capture))
        self._event.set()

    def _on_response(self, response: Any) -> None:
        url = urlsplit(response.url)
        if url.hostname not in selectors.API_HOSTS:
            return
        kind = next((item for item in selectors.PATHS if url.path.endswith("/" + item)), None)
        headers = {key.lower() for key in response.headers}
        risky = response.status in selectors.RISK_STATUSES or bool(
            headers & {"verifytype", "verifyuuid"}
        )
        if kind or risky:
            self._spawn(self._capture_response(response, kind or url.path.lstrip("/")))

    def _on_navigated(self, frame: Any) -> None:
        if frame is not self.page.main_frame:
            return
        capture = Capture(
            platform="xhs",
            kind=selectors.NAVIGATE,
            url_path=urlsplit(frame.url).path,
            body={"path": urlsplit(frame.url).path},
            captured_at=SystemClock().now_ms(),
        )
        self._spawn(self._record(capture))

    async def _capture_response(self, response: Any, kind: str) -> None:
        url = urlsplit(response.url)
        try:
            body = await response.json()
        except Exception:
            try:
                body = (await response.text())[:4096]
            except Exception:
                # 换页后上一页没读完的正文就取不到了（B 站长测实测）；靠状态码就能判的照常上报。
                if response.status not in selectors.RISK_STATUSES:
                    return
                body = ""
        capture = Capture(
            platform="xhs",
            kind=kind,
            url_path=url.path,
            query=dict(parse_qsl(url.query)),
            status=response.status,
            headers={
                key.lower(): value
                for key, value in response.headers.items()
                if key.lower() in selectors.HEADERS
            },
            body=body,
            captured_at=SystemClock().now_ms(),
        )
        await self._record(capture)

    async def _record(self, capture: Capture) -> None:
        async with self._lock:
            if self._failure:
                raise self._failure
            verdict = judge(capture)
            if verdict:
                self._failure = RiskDetected(verdict)
                raise self._failure
            if capture.kind not in selectors.UNSAVED:
                await self.ctx.sink.save(capture)
            self.captures.append(capture)
            self._event.set()

    async def _drain(self) -> None:
        while self._tasks:
            tasks, self._tasks = self._tasks, []
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    raise result

    async def _wait(self, kind: str, start: int, seconds: float) -> Capture | None:
        deadline = asyncio.get_running_loop().time() + seconds
        while True:
            self._event.clear()
            await self._drain()
            found = next((item for item in self.captures[start:] if item.kind == kind), None)
            remaining = deadline - asyncio.get_running_loop().time()
            if found is not None or remaining <= 0:
                return found
            with suppress(TimeoutError):
                await asyncio.wait_for(self._event.wait(), remaining)

    # ---------- 页面操作 ----------

    async def _goto(self, url: str) -> None:
        await self.ctx.pacer.wait("page")
        self.modal = False
        await goto(self.page, url)
        state = None
        for _ in range(20):
            state = await self.page.evaluate(selectors.USER_STATE)
            if state is not None:
                break
            await asyncio.sleep(0.5)
        await self._drain()
        if not isinstance(state, dict):
            raise PageChanged("missing_ssr", selectors.SSR_USER)
        await self._record(
            Capture(
                platform="xhs",
                kind=selectors.SSR_USER,
                url_path=urlsplit(self.page.url).path,
                body=state,
                captured_at=SystemClock().now_ms(),
            )
        )

    async def open_home(self) -> None:
        """探活：打开首页，用 SSR 的登录态判定；没登录时抛 RiskDetected（risk_and_login）。"""
        await self._goto(selectors.HOME)

    async def _choose(self, label: str, start: int) -> Capture:
        """在"筛选"面板里点一个选项，等页面重新搜索。面板悬停才展开，鼠标移开就收起。"""
        await self.ctx.pacer.wait("page")
        await self.page.evaluate(selectors.SCROLL_TOP)
        await self.page.mouse.move(*selectors.MOUSE_REST, steps=5)
        await self.page.locator(selectors.FILTER_BUTTON).first.hover()
        await asyncio.sleep(1.2)
        tag = self.page.locator(selectors.FILTER_TAG.format(label=label)).first
        try:
            box = await tag.bounding_box(timeout=5000)
        except PlaywrightTimeout:
            # 悬停偶尔展不开面板（2026-11-06 实测），重新搜一次就好，不算页面改版。
            raise TransientError("filter_timeout") from None
        if box is None:
            raise PageChanged("missing_filter", label)
        await self.page.mouse.move(
            box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=12
        )
        await asyncio.sleep(0.4)
        await self.page.mouse.down()
        await asyncio.sleep(0.08)
        await self.page.mouse.up()
        capture = await self._wait(selectors.SEARCH, start, 10)
        # 鼠标停在面板上它就不收起，会挡住结果卡片（2026-11-03 实测）。
        await self.page.mouse.move(*selectors.MOUSE_REST, steps=8)
        await asyncio.sleep(1)
        if capture is None:
            raise PageChanged("missed_responses", "filter")
        return capture

    async def search_pages(
        self, keyword: str, sort: SortOrder, time_range: TimeRange | None, now_ms: int
    ) -> AsyncGenerator[Capture]:
        start = len(self.captures)
        await self._goto(selectors.SEARCH_URL + quote(keyword))
        capture = await self._wait(selectors.SEARCH, start, 15)
        if capture is None:
            raise PageChanged("missed_responses", "search")
        # 浏览器跑在本机，"今天"按本机时区算，与执行器的采后过滤一致。
        option = filter_option(time_range, now_ms)
        for label in (
            selectors.SORT[sort] if sort != "default" else None,
            selectors.TIME_FILTER[option] if option else None,
        ):
            if label is not None:
                capture = await self._choose(label, len(self.captures))
        while True:
            yield capture
            if _data(capture).get("has_more") is not True:
                return
            start = len(self.captures)
            await self.ctx.pacer.wait("page")

            async def received(seconds: float, offset: int = start) -> bool:
                return await self._wait(selectors.SEARCH, offset, seconds) is not None

            await scroll_until(self.page, received)
            found = await self._wait(selectors.SEARCH, start, 0.1)
            assert found is not None
            capture = found

    async def reopen_results(
        self, keyword: str, sort: SortOrder, time_range: TimeRange | None
    ) -> None:
        """回到结果页：按原来的条件重新搜索，停在第一页。"""
        pages = self.search_pages(keyword, sort, time_range, SystemClock().now_ms())
        await anext(pages)
        await pages.aclose()

    async def find_card(self, note_id: str, pages: int) -> bool:
        """在当前结果页上找这张卡片，途中最多让页面再翻 `pages` 页。

        搜索响应刚到时卡片可能还没画出来，所以先等；虚拟列表只留视口附近的卡片，
        滚过去的不在 DOM 里，所以再回到顶部往下找。滚到底页面会自己翻页，
        每一页都是一次搜索请求，所以限页数，并按页面间隔走。
        """
        if not urlsplit(self.page.url).path.startswith(selectors.SEARCH_PATH):
            return False
        card = self.page.locator(selectors.CARD.format(id=note_id))

        async def rendered(seconds: float) -> bool:
            for _ in range(round(seconds / selectors.CARD_POLL_SECONDS)):
                if await card.count():
                    return True
                await asyncio.sleep(selectors.CARD_POLL_SECONDS)
            return await card.count() > 0

        if await rendered(selectors.CARD_RENDER_SECONDS):
            return True
        await self.page.evaluate(selectors.SCROLL_TOP)
        if await rendered(1.5):
            return True
        start = len(self.captures)
        loaded = 0

        async def done(seconds: float) -> bool:
            nonlocal loaded
            if await rendered(seconds):
                return True
            await self._drain()
            seen = sum(item.kind == selectors.SEARCH for item in self.captures[start:])
            if loaded < seen < pages:
                await self.ctx.pacer.wait("page")
            loaded = seen
            return loaded >= pages

        with suppress(PageChanged):
            await scroll_until(self.page, done, max_steps=selectors.CARD_SCROLL_STEPS)
        return await card.count() > 0

    async def open_note(self, ref: ContentRef, depth: Depth, *, from_card: bool) -> None:
        """打开一篇笔记，在同一页里拿完详情、一级评论和二级评论。"""
        start = len(self.captures)
        if from_card:
            card = self.page.locator(selectors.CARD.format(id=ref.platform_id))
            await self.ctx.pacer.wait("page")
            await self.page.mouse.move(*selectors.MOUSE_REST, steps=5)
            await card.first.scroll_into_view_if_needed()
            await asyncio.sleep(1)
            await card.first.click()
            self.modal = True
            detail = await self._wait(selectors.FEED, start, 15)
            if detail is None:
                raise PageChanged("missed_responses", "feed")
        else:
            await self._goto(with_token(selectors.NOTE_URL + ref.platform_id, ref.ext))
            body = None
            for _ in range(20):
                body = await self.page.evaluate(selectors.NOTE_STATE, ref.platform_id)
                if body is not None:
                    break
                await asyncio.sleep(0.5)
            if not isinstance(body, dict):
                raise PageChanged("missing_ssr", selectors.SSR_NOTE)
            await self._record(
                Capture(
                    platform="xhs",
                    kind=selectors.SSR_NOTE,
                    url_path=urlsplit(self.page.url).path,
                    body=body,
                    captured_at=SystemClock().now_ms(),
                )
            )
        if depth.comments > 0:
            await self._comments(depth, start)

    async def _comments(self, depth: Depth, start: int) -> None:
        capture = await self._wait(selectors.COMMENTS, start, 10)
        if capture is None:
            raise PageChanged("missed_responses", "comments")
        count = 0
        while True:
            comments = _data(capture).get("comments")
            if not isinstance(comments, list):
                raise PageChanged("missing_comments")
            roots = [item for item in comments if isinstance(item, dict)]  # pyright: ignore[reportUnknownVariableType]
            if depth.sub_comments and depth.sub_comments_per_root > 0:
                for root in roots[: max(0, depth.comments - count)]:  # pyright: ignore[reportUnknownVariableType]
                    await self._sub_comments(root, depth.sub_comments_per_root)  # pyright: ignore[reportUnknownArgumentType]
            count += len(roots)  # pyright: ignore[reportUnknownArgumentType]
            if count >= depth.comments or _data(capture).get("has_more") is not True:
                return
            # 展开二级评论会滚动评论区，常顺带加载下一页（2026-11-03 实测），先用已经到了的那页。
            offset = self.captures.index(capture) + 1
            found = await self._wait(selectors.COMMENTS, offset, 0.1)
            if found is None:
                await self.ctx.pacer.wait("comment_page")

                async def received(seconds: float, offset: int = offset) -> bool:
                    return await self._wait(selectors.COMMENTS, offset, seconds) is not None

                await scroll_until(
                    self.page,
                    received,
                    scroll=selectors.SCROLL_COMMENTS,
                    at_bottom=selectors.COMMENTS_AT_BOTTOM,
                )
                found = await self._wait(selectors.COMMENTS, offset, 0.1)
            assert found is not None
            capture = found

    async def _sub_comments(self, root: dict[str, Any], limit: int) -> None:
        collected = len(root.get("sub_comments") or [])
        more = root.get("sub_comment_has_more") is True
        while more and collected < limit:
            await self.ctx.pacer.wait("comment_page")
            offset = len(self.captures)
            button = self.page.locator(selectors.SHOW_MORE.format(id=root.get("id"))).first
            if not await button.count():
                raise PageChanged("missing_show_more", str(root.get("id")))
            await button.scroll_into_view_if_needed()
            await button.click()
            capture = await self._wait(selectors.SUB_COMMENTS, offset, 10)
            if capture is None:
                raise PageChanged("missed_responses", "sub_comments")
            data = _data(capture)
            replies = data.get("comments")
            if not isinstance(replies, list):
                raise PageChanged("missing_comments", "sub")
            collected += len(replies)  # pyright: ignore[reportUnknownArgumentType]
            more = data.get("has_more") is True

    async def close_note(self) -> None:
        if self.modal:
            await self.page.keyboard.press("Escape")
            self.modal = False
            await asyncio.sleep(1)

    async def close(self) -> None:
        self.page.remove_listener("response", self._on_response)
        self.page.remove_listener("framenavigated", self._on_navigated)
        await self._drain()
