from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any, Protocol
from urllib.parse import parse_qsl, quote, urlsplit

from gleanery.clock import SystemClock
from gleanery.platforms.bili import selectors
from gleanery.platforms.bili.risk import judge
from gleanery.platforms.errors import PageChanged, RiskDetected
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


class Page(Protocol):
    url: str
    context: Any

    def on(self, event: str, callback: Callable[..., None]) -> Any: ...
    def remove_listener(self, event: str, callback: Callable[..., None]) -> Any: ...
    async def goto(self, url: str, *, wait_until: str) -> Any: ...
    async def evaluate(self, expression: str, arg: Any = None) -> Any: ...
    async def evaluate_handle(self, expression: str, arg: Any = None) -> Any: ...
    def locator(self, selector: str) -> Any: ...
    def get_by_text(self, text: str, *, exact: bool = False) -> Any: ...


def original_tracks(tracks: Any) -> list[dict[str, Any]]:
    """去掉机器翻译的字幕轨，只留人工字幕和 AI 识别的原声字幕。

    2026-11-02 实测：AI 字幕轨里 ai_type 0 是识别原声，1 是机器翻译；一个视频带了 7 种译文。
    """
    if not isinstance(tracks, list):
        return []
    return [
        track
        for track in tracks  # pyright: ignore[reportUnknownVariableType]
        if isinstance(track, dict) and track.get("ai_type") != 1  # pyright: ignore[reportUnknownMemberType]
    ]


def pubtime_window(
    time_range: TimeRange | None, now_ms: int, tz: tzinfo | None = None
) -> tuple[int, int] | None:
    """把时间范围换成搜索页发布时间筛选的起止秒（含两端），按本地日期算，与执行器的采后过滤一致。

    只写结束日期、日期写错时返回 None，不设筛选，由采后过滤兜底。
    """
    if time_range is None:
        return None
    today = datetime.fromtimestamp(now_ms / 1000, tz).date()
    try:
        lowers = [date.fromisoformat(time_range.start)] if time_range.start else []
        uppers = [date.fromisoformat(time_range.end)] if time_range.end else []
    except ValueError:
        return None
    if time_range.last_days is not None:
        lowers.append(today - timedelta(days=time_range.last_days - 1))
        uppers.append(today)
    if not lowers:
        return None
    first, last = max(lowers), min(uppers, default=today)

    def midnight(day: date) -> int:
        return int(datetime.combine(day, time.min, tzinfo=tz).timestamp())

    return midnight(first), midnight(last + timedelta(days=1)) - 1


class BiliDriver:
    def __init__(self, page: Page, ctx: FetchContext) -> None:
        self.page, self.ctx = page, ctx
        self._tasks: list[asyncio.Task[None]] = []
        self._captures: list[Capture] = []
        self._event = asyncio.Event()
        self._failure: BaseException | None = None
        self._lock = asyncio.Lock()
        self.page.on("response", self._on_response)

    def _on_response(self, response: Any) -> None:
        path = urlsplit(response.url).path
        kind = next((item for item in selectors.PATHS if path.endswith("/" + item)), None)
        if kind or response.status == 412:
            kind = kind or path.lstrip("/")
            self._tasks.append(asyncio.create_task(self._capture_response(response, kind)))
            self._event.set()

    async def _capture_response(self, response: Any, kind: str) -> None:
        url = urlsplit(response.url)
        try:
            body = await response.json()
        except Exception:
            try:
                body = (await response.text())[:4096]
            except Exception:
                # 跳到下一页后，上一页还没读完的响应正文就取不到了（2026-11-01 长测实测）。
                # 那页已经不用了，丢掉即可；只有 412 靠状态码就能判风控，照常上报。
                if response.status != 412:
                    return
                body = ""
        capture = Capture(
            platform="bili",
            kind=kind,
            url_path=url.path,
            query={
                key: value for key, value in parse_qsl(url.query) if key not in ("w_rid", "wts")
            },
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
            if capture.kind != selectors.NAV:
                await self.ctx.sink.save(capture)
            self._captures.append(capture)
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
            for capture in self._captures[start:]:
                if capture.kind == kind:
                    return capture
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return None
            try:
                await asyncio.wait_for(self._event.wait(), remaining)
            except TimeoutError:
                await self._drain()
                return next((item for item in self._captures[start:] if item.kind == kind), None)

    async def _goto(self, url: str) -> None:
        await self.ctx.pacer.wait("page")
        start = len(self._captures)
        await goto(self.page, url)
        if await self._wait(selectors.NAV, start, 10) is None:
            raise PageChanged("missing_nav")

    async def _ssr(self, kind: str, expression: str) -> Capture:
        body = await self.page.evaluate(expression)
        await self._drain()
        if not isinstance(body, dict) or (
            kind == "ssr:search" and not isinstance(body.get("result"), list)
        ):
            raise PageChanged("missing_ssr", kind)
        capture = Capture(
            platform="bili",
            kind=kind,
            url_path=urlsplit(self.page.url).path,
            body=body,
            captured_at=SystemClock().now_ms(),
        )
        await self._record(capture)
        return capture

    async def open_home(self) -> None:
        """探活：打开首页，用这次导航的 nav 判定登录态；没登录时抛 RiskDetected（login_required）。"""
        await self._goto(selectors.HOME)

    async def search_pages(
        self, keyword: str, sort: SortOrder = "default", time_range: TimeRange | None = None
    ) -> AsyncIterator[Capture]:
        url = selectors.SEARCH_URL + quote(keyword)
        # 浏览器跑在本机，页面按本机时区换算日期，这里也用本机时区。
        window = pubtime_window(time_range, SystemClock().now_ms())
        if window is not None:
            url += f"&{selectors.PUBTIME_BEGIN}={window[0]}&{selectors.PUBTIME_END}={window[1]}"
        await self._goto(url)
        if sort != "default":
            start = len(self._captures)
            await self.ctx.pacer.wait("page")
            await self.page.get_by_text(selectors.SORT[sort], exact=True).click()
            capture = await self._wait(selectors.SEARCH, start, 5)
            if capture is None:
                raise PageChanged("missed_responses")
        else:
            capture = await self._ssr("ssr:search", selectors.SEARCH_STATE)
        yield capture
        while True:
            body = capture.body
            data = body.get("data", body) if isinstance(body, dict) else {}
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("numPages"), int)
                or not isinstance(data.get("page"), int)
            ):
                raise PageChanged("missing_pagination")
            if data["page"] >= data["numPages"]:
                return
            start = len(self._captures)
            await self.ctx.pacer.wait("page")
            await self.page.get_by_text(
                selectors.NEXT_PAGE.removeprefix("text="), exact=True
            ).click()
            capture = await self._wait(selectors.SEARCH, start, 5)
            if capture is None:
                raise PageChanged("missed_responses")
            yield capture

    async def open_video(self, ref: ContentRef, depth: Depth) -> Capture:
        start = len(self._captures)
        await self._goto(ref.url)
        video = await self._ssr("ssr:video", selectors.VIDEO_STATE)
        if depth.subtitles:
            player = await self._wait(selectors.PLAYER, start, 10)
            if player is None:
                raise PageChanged("missing_player")
            data = player.body.get("data", {}) if isinstance(player.body, dict) else {}
            subtitle = data.get("subtitle", {}) if isinstance(data, dict) else {}
            tracks = subtitle.get("subtitles", []) if isinstance(subtitle, dict) else []
            # 字幕截获自带所属视频与分 P，解析器是单条截获的纯函数，靠它们关联内容。
            cid = video.body.get("cid") if isinstance(video.body, dict) else None
            pages = video.body.get("pages") if isinstance(video.body, dict) else None
            part = next(
                (
                    item.get("part")
                    for item in pages or []
                    if isinstance(item, dict) and item.get("cid") == cid
                ),
                None,
            )
            owner = {"bvid": ref.platform_id, "cid": cid, "part": part}
            for track in original_tracks(tracks):
                url = track.get("subtitle_url")
                if not isinstance(url, str) or not url:
                    continue
                result = await self.page.evaluate(
                    selectors.SUBTITLE_FETCH, "https:" + url if url.startswith("//") else url
                )
                try:
                    body = json.loads(result["body"])
                except (ValueError, TypeError):
                    body = result["body"][:4096]
                capture = Capture(
                    platform="bili",
                    kind="subtitle",
                    url_path=urlsplit(url).path,
                    status=result["status"],
                    body={**owner, "track": track, "body": body},
                    captured_at=SystemClock().now_ms(),
                )
                await self._record(capture)
        if depth.comments > 0:
            await self.ctx.pacer.wait("comment_page")
            await self.page.locator(selectors.COMMENT_AREA).scroll_into_view_if_needed()
            count = 0
            while count < depth.comments:
                before = start
                await self._drain()
                existing = next(
                    (item for item in self._captures[before:] if item.kind == selectors.COMMENTS),
                    None,
                )
                if existing is None:
                    await self.ctx.pacer.wait("comment_page")

                    async def received(seconds: float, offset: int = before) -> bool:
                        return await self._wait(selectors.COMMENTS, offset, seconds) is not None

                    await scroll_until(self.page, received)
                    existing = await self._wait(selectors.COMMENTS, before, 0.1)
                if existing is None or not isinstance(existing.body, dict):
                    raise PageChanged("missing_comments")
                start = self._captures.index(existing) + 1
                data = existing.body.get("data")
                if not isinstance(data, dict) or not isinstance(data.get("cursor"), dict):
                    raise PageChanged("missing_comments")
                replies = data.get("replies") or []
                count += len(replies)
                if depth.sub_comments and depth.sub_comments_per_root > 0:
                    for root in replies[: max(0, depth.comments - (count - len(replies)))]:
                        if isinstance(root, dict):
                            await self._sub_replies(root, depth.sub_comments_per_root)
                if data["cursor"].get("is_end") is True:
                    break
        await self._drain()
        return video

    async def _click(self, expression: str, rpid: str) -> bool:
        handle = await self.page.evaluate_handle(expression, rpid)
        element = handle.as_element()
        if element is None:
            await handle.dispose()
            return False
        await element.click()
        return True

    async def _sub_replies(self, root: dict[str, Any], limit: int) -> None:
        rcount = root.get("rcount") or 0
        preview = root.get("replies") or []
        # 回复不多时评论接口已经带全了，页面也没有"点击查看"。
        if rcount <= len(preview):
            return
        rpid = str(root.get("rpid_str") or root.get("rpid"))
        await self.ctx.pacer.wait("comment_page")
        start = len(self._captures)
        if not await self._click(selectors.REPLY_BUTTON, rpid):
            raise PageChanged("missing_reply_button", rpid)
        collected = 0
        while True:
            capture = await self._wait(selectors.REPLIES, start, 5)
            if capture is None:
                raise PageChanged("missed_responses")
            start = self._captures.index(capture) + 1
            data = capture.body.get("data") if isinstance(capture.body, dict) else None
            if not isinstance(data, dict) or not isinstance(data.get("page"), dict):
                raise PageChanged("missing_pagination")
            collected += len(data.get("replies") or [])
            num, size, total = (data["page"].get(key) for key in ("num", "size", "count"))
            if not (isinstance(num, int) and isinstance(size, int) and isinstance(total, int)):
                raise PageChanged("missing_pagination")
            if collected >= limit or num * size >= total:
                return
            await self.ctx.pacer.wait("comment_page")
            if not await self._click(selectors.REPLY_NEXT_PAGE, rpid):
                raise PageChanged("missing_reply_next_page", rpid)

    async def close(self) -> None:
        self.page.remove_listener("response", self._on_response)
        await self._drain()
