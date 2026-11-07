from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest

from gleanery.platforms.bili import selectors
from gleanery.platforms.bili.driver import BiliDriver
from gleanery.platforms.errors import PageChanged, RiskDetected
from gleanery.platforms.types import Capture, ContentRef, Depth, FetchContext, TimeRange


class Sink:
    def __init__(self) -> None:
        self.captures: list[Capture] = []

    async def save(self, capture: Capture) -> None:
        self.captures.append(capture)


class Context:
    def __init__(self) -> None:
        self.sink = Sink()
        self.pacer = self
        self.waits: list[str] = []

    async def wait(self, kind: Any) -> None:
        self.waits.append(kind)

    def log(self, message: str) -> None:
        pass


class Response:
    def __init__(self, path: str, body: Any, status: int = 200) -> None:
        self.url = "https://example.test/" + path + "?w_rid=secret&wts=123&page=2"
        self.status = status
        self.headers = {"set-cookie": "secret"}
        self.body = body

    async def json(self) -> Any:
        if isinstance(self.body, str):
            raise ValueError()
        return self.body

    async def text(self) -> str:
        return str(self.body)


class FakePage:
    url = ""
    context: Any = None

    def __init__(self) -> None:
        self.callback: Any = None
        self.next_response: Response | None = None

    def on(self, event: str, callback: Any) -> None:
        self.callback = callback

    def remove_listener(self, event: str, callback: Any) -> None:
        self.callback = None

    async def goto(self, url: str, *, wait_until: str) -> None:
        assert wait_until == "domcontentloaded"
        self.url = url
        self.callback(Response(selectors.NAV, {"data": {"isLogin": True}}))

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        return {"result": [], "page": 1, "numPages": 2}

    async def evaluate_handle(self, expression: str, arg: Any = None) -> Any:
        raise AssertionError("未预期的元素查找")

    def get_by_text(self, text: str, *, exact: bool = False) -> Any:
        return self

    def locator(self, selector: str) -> Any:
        return self

    async def click(self) -> None:
        assert self.next_response is not None
        self.callback(self.next_response)


async def test_search_and_redaction() -> None:
    page, ctx = FakePage(), Context()
    page.next_response = Response(selectors.SEARCH, {"data": {"page": 2, "numPages": 2}})
    driver = BiliDriver(page, cast(FetchContext, ctx))
    pages = [capture async for capture in driver.search_pages("测试")]
    assert [capture.kind for capture in pages] == ["ssr:search", selectors.SEARCH]
    assert pages[1].query == {"page": "2"} and pages[1].headers == {}
    assert all(capture.kind != selectors.NAV for capture in ctx.sink.captures)
    assert ctx.waits == ["page", "page"]
    await driver.close()


async def test_search_url_carries_pubtime_filter() -> None:
    page, ctx = FakePage(), Context()
    driver = BiliDriver(page, cast(FetchContext, ctx))
    async for _ in driver.search_pages("测试", time_range=TimeRange(last_days=30)):
        break
    query = parse_qs(urlsplit(page.url).query)
    begin, end = int(query[selectors.PUBTIME_BEGIN][0]), int(query[selectors.PUBTIME_END][0])
    # 30 个本地日，跨夏令时切换时差一小时。
    assert abs(end + 1 - begin - 30 * 86400) <= 3600
    async for _ in driver.search_pages("测试", time_range=TimeRange(end="2026-10-01")):
        break
    assert selectors.PUBTIME_BEGIN not in page.url
    await driver.close()


async def test_html_412_stops() -> None:
    page, ctx = FakePage(), Context()
    driver = BiliDriver(page, cast(FetchContext, ctx))
    page.callback(Response(selectors.SEARCH, "blocked", 412))
    with pytest.raises(RiskDetected):
        await driver.close()
    assert not ctx.sink.captures


class GoneResponse(Response):
    """离开页面后才去读正文的响应：Playwright 报 "No resource with given identifier found"。"""

    async def json(self) -> Any:
        raise RuntimeError("No resource with given identifier found")

    async def text(self) -> str:
        raise RuntimeError("No resource with given identifier found")


async def test_body_gone_after_navigation_is_dropped() -> None:
    page, ctx = FakePage(), Context()
    driver = BiliDriver(page, cast(FetchContext, ctx))
    page.callback(GoneResponse(selectors.COMMENTS, None))
    await driver.open_video(
        ContentRef(platform="bili", platform_id="BV1tYWA6DEmS", url="https://example.test/v"),
        Depth(detail=False, comments=0, sub_comments=False, subtitles=False),
    )
    assert all(capture.kind != selectors.COMMENTS for capture in ctx.sink.captures)
    await driver.close()


async def test_412_without_body_still_stops() -> None:
    page, ctx = FakePage(), Context()
    driver = BiliDriver(page, cast(FetchContext, ctx))
    page.callback(GoneResponse(selectors.SEARCH, None, 412))
    with pytest.raises(RiskDetected):
        await driver.close()


async def test_missing_search_ssr() -> None:
    class ChangedPage(FakePage):
        async def evaluate(self, expression: str, arg: Any = None) -> Any:
            return None

    page, ctx = ChangedPage(), Context()
    driver = BiliDriver(page, cast(FetchContext, ctx))
    with pytest.raises(PageChanged, match="missing_ssr"):
        _ = [capture async for capture in driver.search_pages("测试")]
    await driver.close()


async def test_video_and_subtitle() -> None:
    class VideoPage(FakePage):
        async def goto(self, url: str, *, wait_until: str) -> None:
            await super().goto(url, wait_until=wait_until)
            self.callback(
                Response(
                    selectors.PLAYER,
                    {
                        "data": {
                            "subtitle": {"subtitles": [{"subtitle_url": "//cdn.example/sub.json"}]}
                        }
                    },
                )
            )

        async def evaluate(self, expression: str, arg: Any = None) -> Any:
            if expression == selectors.VIDEO_STATE:
                return {"bvid": "BV1tYWA6DEmS", "cid": 7, "pages": [{"cid": 7, "part": "P1"}]}
            assert arg == "https://cdn.example/sub.json"
            return {"status": 200, "body": '{"body": []}'}

    page, ctx = VideoPage(), Context()
    driver = BiliDriver(page, cast(FetchContext, ctx))
    video = await driver.open_video(
        ContentRef(
            platform="bili",
            platform_id="BV1tYWA6DEmS",
            url="https://www.bilibili.com/video/BV1tYWA6DEmS",
        ),
        Depth(subtitles=True),
    )
    assert video.kind == "ssr:video"
    subtitle = next(item for item in ctx.sink.captures if item.kind == "subtitle")
    assert subtitle.body["bvid"] == "BV1tYWA6DEmS" and subtitle.body["cid"] == 7
    assert subtitle.body["part"] == "P1"
    await driver.close()


def reply_page(num: int, replies: int) -> Response:
    return Response(
        selectors.REPLIES,
        {
            "code": 0,
            "data": {"page": {"num": num, "size": 10, "count": 15}, "replies": [{}] * replies},
        },
    )


class CommentPage(FakePage):
    def __init__(self) -> None:
        super().__init__()
        self.clicks: list[tuple[str, str]] = []
        self.reply_pages = [reply_page(1, 10), reply_page(2, 5)]

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        if expression == selectors.VIDEO_STATE:
            return {"bvid": "BV1tYWA6DEmS"}
        # 滚到评论区，评论接口返回一页：一条回复少（接口已带全），一条要展开再翻页。
        self.callback(
            Response(
                selectors.COMMENTS,
                {
                    "code": 0,
                    "data": {
                        "cursor": {"is_end": True},
                        "replies": [
                            {"rpid": 1, "rpid_str": "1", "rcount": 2, "replies": [{}, {}]},
                            {"rpid": 2, "rpid_str": "2", "rcount": 15, "replies": [{}, {}, {}]},
                        ],
                    },
                },
            )
        )

    async def evaluate_handle(self, expression: str, arg: Any = None) -> Any:
        page = self

        class Element:
            async def click(self) -> None:
                page.clicks.append((expression, arg))
                page.callback(page.reply_pages.pop(0))

        class Handle:
            def as_element(self) -> Any:
                return Element()

            async def dispose(self) -> None:
                pass

        return Handle()

    async def scroll_into_view_if_needed(self) -> None:
        pass


async def test_comments_expand_and_page_sub_replies() -> None:
    page, ctx = CommentPage(), Context()
    driver = BiliDriver(page, cast(FetchContext, ctx))
    await driver.open_video(
        ContentRef(platform="bili", platform_id="BV1tYWA6DEmS", url="https://example.test/v"),
        Depth(comments=20, sub_comments=True, sub_comments_per_root=20),
    )
    assert page.clicks == [(selectors.REPLY_BUTTON, "2"), (selectors.REPLY_NEXT_PAGE, "2")]
    kinds = [capture.kind for capture in ctx.sink.captures]
    assert kinds == ["ssr:video", selectors.COMMENTS, selectors.REPLIES, selectors.REPLIES]
    await driver.close()


async def test_sub_replies_stop_at_limit() -> None:
    page, ctx = CommentPage(), Context()
    driver = BiliDriver(page, cast(FetchContext, ctx))
    await driver.open_video(
        ContentRef(platform="bili", platform_id="BV1tYWA6DEmS", url="https://example.test/v"),
        Depth(comments=20, sub_comments=True, sub_comments_per_root=10),
    )
    assert page.clicks == [(selectors.REPLY_BUTTON, "2")]
    await driver.close()
