"""打开笔记走哪条路径：用假结果页复现卡片滚过去和还没渲染的现场。"""

import asyncio
import copy
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeout

from gleanery.browser.manager import BrowserManager
from gleanery.platforms.errors import RiskDetected, TransientError
from gleanery.platforms.types import Capture, ContentRef, Depth, FetchContext, TimeRange
from gleanery.platforms.xhs import selectors
from gleanery.platforms.xhs.fetcher import XhsFetcher

ROOT = Path(__file__).parents[2] / "fixtures" / "xhs"
CARD_HEIGHT = 30
RENDERED_CARDS = 25
"""假结果页的虚拟列表：DOM 里只留视口附近这么多张卡片，要比滚动一步的 600 像素高。"""
VIEWPORT = 120
PAGE_SIZE = 20
TOKEN = "SECRET-TOKEN"


def fixture(kind: str, case: str = "normal") -> dict[str, Any]:
    return json.loads((ROOT / kind / f"20261103-{case}.json").read_text())["capture"]


def note_id(number: int) -> str:
    return f"{number:024x}"


class Response:
    def __init__(self, path: str, body: Any, status: int = 200) -> None:
        self.url = "https://edith.xiaohongshu.com" + path
        self.status = status
        self.headers = {"content-type": "application/json"}
        self.body = body

    async def json(self) -> Any:
        return self.body

    async def text(self) -> str:
        return json.dumps(self.body)


class Card:
    def __init__(self, site: "FakeSite", note: str) -> None:
        self.site, self.note = site, note

    @property
    def first(self) -> "Card":
        return self

    async def count(self) -> int:
        return 1 if self.note in self.site.rendered() else 0

    async def scroll_into_view_if_needed(self) -> None:
        assert await self.count()

    async def click(self) -> None:
        assert await self.count()
        self.site.clicked.append(self.note)
        self.site.emit(Response("/api/sns/web/v1/feed", fixture("feed")["body"]))


class Control:
    """筛选按钮和选项：结果页只用到悬停和取位置。"""

    @property
    def first(self) -> "Control":
        return self

    async def hover(self) -> None:
        pass

    async def bounding_box(self, **kwargs: Any) -> dict[str, float]:
        return {"x": 0, "y": 0, "width": 10, "height": 10}


class StuckControl(Control):
    """悬停后面板没展开，选项一直不出现。"""

    async def bounding_box(self, **kwargs: Any) -> dict[str, float]:
        raise PlaywrightTimeout("Locator.bounding_box: Timeout 5000ms exceeded.")


class Mouse:
    def __init__(self, site: "FakeSite") -> None:
        self.site = site

    async def move(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def down(self) -> None:
        pass

    async def up(self) -> None:
        assert self.site.pending_filter is not None
        self.site.filters.append(self.site.pending_filter)
        self.site.loaded = 0
        self.site.load_page()


class Keyboard:
    def __init__(self, site: "FakeSite") -> None:
        self.site = site

    async def press(self, key: str) -> None:
        assert key == "Escape"


class FakeSite:
    context: Any = None
    main_frame: Any = "main"

    def __init__(self, results: dict[str, list[list[str]]], render_delay: float = 0) -> None:
        self.results = results
        self.render_delay = render_delay
        self.now = 0.0
        self.url = "about:blank"
        self.keyword: str | None = None
        self.loaded = 0
        self.scroll = 0
        self.ready_at = 0.0
        self.searches: list[str] = []
        self.filters: list[str] = []
        self.pending_filter: str | None = None
        self.clicked: list[str] = []
        self.direct: list[str] = []
        self.direct_urls: list[str] = []
        self.next_search_response: Response | None = None
        self.hidden: set[str] = set()
        """结果里有、页面上却始终找不到的卡片。"""
        self.broken_search = False
        self.stuck_filter = False
        self.mouse = Mouse(self)
        self.keyboard = Keyboard(self)
        self.handlers: dict[str, Any] = {}

    def on(self, event: str, callback: Any) -> None:
        self.handlers[event] = callback

    def remove_listener(self, event: str, callback: Any) -> None:
        self.handlers.pop(event, None)

    def emit(self, response: Response) -> None:
        self.handlers["response"](response)

    def is_results(self) -> bool:
        return urlsplit(self.url).path.startswith(selectors.SEARCH_PATH)

    def notes(self) -> list[str]:
        assert self.keyword is not None
        return [item for page in self.results[self.keyword][: self.loaded] for item in page]

    def rendered(self) -> list[str]:
        if not self.is_results() or self.now < self.ready_at:
            return []
        first = max(0, self.scroll // CARD_HEIGHT - 2)
        window = self.notes()[first : first + RENDERED_CARDS]
        return [item for item in window if item not in self.hidden]

    def load_page(self) -> None:
        assert self.keyword is not None
        pages = self.results[self.keyword]
        self.searches.append(self.keyword)
        self.ready_at = self.now + self.render_delay
        if self.next_search_response is not None:
            response, self.next_search_response = self.next_search_response, None
            self.emit(response)
            return
        template = fixture("search__notes")["body"]["data"]["items"][0]
        items = []
        for item in pages[self.loaded]:
            entry = copy.deepcopy(template)
            entry["id"], entry["xsec_token"] = item, TOKEN
            items.append(entry)
        self.loaded += 1
        self.emit(
            Response(
                "/api/sns/web/v2/search/notes",
                {
                    "code": 0,
                    "success": True,
                    "data": {"has_more": self.loaded < len(pages), "items": items},
                },
            )
        )

    async def goto(self, url: str, *, wait_until: str) -> None:
        self.url = url
        self.handlers["framenavigated"](SimpleFrame(url, self))
        path = urlsplit(url).path
        if path.startswith(selectors.SEARCH_PATH):
            self.keyword = parse_qs(urlsplit(url).query)["keyword"][0]
            self.loaded, self.scroll = 0, 0
            self.load_page()
        else:
            self.direct.append(path.rsplit("/", 1)[-1])
            self.direct_urls.append(url)

    async def evaluate(self, expression: str, arg: Any = None) -> Any:
        if expression == selectors.USER_STATE:
            return (
                None
                if self.broken_search and self.is_results()
                else {
                    "logged_in": True,
                    "guest": False,
                }
            )
        if expression == selectors.NOTE_STATE:
            return fixture("ssr__note")["body"]
        if "scrollTo(0, 0)" in expression:
            self.scroll = 0
            return None
        if "scrollBy" in expression:
            self.scroll += arg
            bottom = self.loaded * PAGE_SIZE * CARD_HEIGHT
            assert self.keyword is not None
            if self.scroll + VIEWPORT >= bottom - 100 and self.loaded < len(
                self.results[self.keyword]
            ):
                self.load_page()
            return None
        if "innerHeight" in expression:
            return self.scroll + VIEWPORT >= len(self.notes()) * CARD_HEIGHT - 100
        raise AssertionError(expression)

    def locator(self, selector: str) -> Any:
        found = re.search(r'href\*="(\w+)"', selector)
        if found:
            return Card(self, found.group(1))
        label = re.search(r'text="(.+?)"', selector)
        if label:
            self.pending_filter = label.group(1)
            if self.stuck_filter:
                return StuckControl()
        return Control()


class SimpleFrame:
    def __init__(self, url: str, site: FakeSite) -> None:
        self.url = url
        self.site = site


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
        self.logs: list[str] = []

    async def wait(self, kind: Any) -> None:
        self.waits.append(kind)

    def log(self, message: str) -> None:
        self.logs.append(message)


class Manager:
    def __init__(self, site: FakeSite) -> None:
        self.site = site

    @asynccontextmanager
    async def page(self, platform: str) -> AsyncIterator[FakeSite]:
        yield self.site


@pytest.fixture(autouse=True)
def fast_time(monkeypatch: pytest.MonkeyPatch) -> list[FakeSite]:
    """驱动里的等待都走假时钟，页面的渲染进度跟着它走。"""
    sites: list[FakeSite] = []
    real = asyncio.sleep

    async def sleep(seconds: float, result: Any = None) -> Any:
        for site in sites:
            site.now += seconds
        return await real(0, result)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    return sites


def ref(note: str) -> ContentRef:
    return ContentRef(
        platform="xhs",
        platform_id=note,
        url=selectors.NOTE_URL + note,
        ext={"xsec_token": TOKEN, "xsec_source": "pc_search"},
    )


def fetcher_for(site: FakeSite, sites: list[FakeSite]) -> XhsFetcher:
    sites.append(site)
    return XhsFetcher(cast(BrowserManager, Manager(site)))


async def search(
    fetcher: XhsFetcher,
    keyword: str,
    ctx: Context,
    pages: int = 1,
    sort: Any = "default",
    time_range: TimeRange | None = None,
) -> None:
    """同执行器：拿够页数就关掉迭代器，页面停在结果页。"""
    iterator = fetcher.search(keyword, sort, time_range, cast(FetchContext, ctx))
    for _ in range(pages):
        await anext(iterator)
    await iterator.aclose()  # pyright: ignore[reportAttributeAccessIssue]


async def collect(fetcher: XhsFetcher, note: str, ctx: Context) -> str | None:
    result = await fetcher.collect_content(ref(note), Depth(comments=0), cast(FetchContext, ctx))
    return result.route


def one_page(*numbers: int) -> dict[str, list[list[str]]]:
    return {"露营": [[note_id(number) for number in numbers]]}


NOT_FOUND = "直接打开：结果页里定位不到卡片"


async def test_waits_for_results_to_render_before_giving_up_on_the_card(
    fast_time: list[FakeSite],
) -> None:
    """第一条就在第 0 位、没滚动过，只是响应刚到、卡片还没画出来。"""
    site, ctx = FakeSite(one_page(1, 2), render_delay=2), Context()
    fetcher = fetcher_for(site, fast_time)
    await search(fetcher, "露营", ctx)

    assert await collect(fetcher, note_id(1), ctx) == "结果页卡片"

    assert site.clicked == [note_id(1)] and site.direct == []


def three_pages() -> dict[str, list[list[str]]]:
    return {
        "露营": [
            [note_id(page * PAGE_SIZE + index + 1) for index in range(PAGE_SIZE)]
            for page in range(3)
        ]
    }


async def test_scrolls_back_to_find_a_card_the_virtual_list_dropped(
    fast_time: list[FakeSite],
) -> None:
    """翻完 3 页再开第一条，虚拟列表已经把它移出 DOM。"""
    site, ctx = FakeSite(three_pages()), Context()
    fetcher = fetcher_for(site, fast_time)
    await search(fetcher, "露营", ctx, pages=3)
    assert note_id(1) not in site.rendered()

    assert await collect(fetcher, note_id(1), ctx) == "结果页卡片"
    # 下一条在卡片附近，不用再回顶部。
    assert await collect(fetcher, note_id(2), ctx) == "结果页卡片"

    assert site.clicked == [note_id(1), note_id(2)] and site.direct == []


async def test_finds_a_card_further_down_than_the_viewport(fast_time: list[FakeSite]) -> None:
    site, ctx = FakeSite(three_pages()), Context()
    fetcher = fetcher_for(site, fast_time)
    await search(fetcher, "露营", ctx, pages=3)
    target = note_id(25)
    assert target not in site.rendered()

    assert await collect(fetcher, target, ctx) == "结果页卡片"

    assert site.clicked == [target] and site.direct == []


async def test_opens_directly_only_when_the_card_cannot_be_located(
    fast_time: list[FakeSite], caplog: pytest.LogCaptureFixture
) -> None:
    site, ctx = FakeSite(one_page(1, 2)), Context()
    site.hidden.add(note_id(1))
    fetcher = fetcher_for(site, fast_time)
    await search(fetcher, "露营", ctx)

    assert await collect(fetcher, note_id(1), ctx) == NOT_FOUND

    assert site.clicked == [] and site.direct == [note_id(1)]
    assert TOKEN in site.direct_urls[0]
    assert note_id(1) in caplog.text and TOKEN not in caplog.text


async def test_looking_for_a_card_loads_no_more_pages_than_the_search_did(
    fast_time: list[FakeSite],
) -> None:
    """找不到的卡片不能把结果页一路翻到底：每翻一页都是一次搜索请求。"""
    site, ctx = FakeSite(three_pages()), Context()
    site.hidden.add(note_id(1))
    fetcher = fetcher_for(site, fast_time)
    await search(fetcher, "露营", ctx, pages=1)

    assert await collect(fetcher, note_id(1), ctx) == NOT_FOUND

    assert len(site.searches) == 2


async def test_comes_back_to_results_after_a_direct_open(fast_time: list[FakeSite]) -> None:
    """长测里一次直开之后全程直开：下一条要先回到结果页，排序和筛选也要照原样。"""
    site, ctx = FakeSite(one_page(1, 2, 3)), Context()
    site.hidden.add(note_id(1))
    fetcher = fetcher_for(site, fast_time)
    await search(fetcher, "露营", ctx, sort="new", time_range=TimeRange(last_days=7))
    assert site.filters == ["最新", "一周内"]

    assert await collect(fetcher, note_id(1), ctx) == NOT_FOUND
    assert await collect(fetcher, note_id(2), ctx) == "结果页卡片"
    assert await collect(fetcher, note_id(3), ctx) == "结果页卡片"

    assert site.filters == ["最新", "一周内", "最新", "一周内"]
    assert site.direct == [note_id(1)] and site.clicked == [note_id(2), note_id(3)]


async def test_reopens_the_results_of_an_earlier_keyword(fast_time: list[FakeSite]) -> None:
    """页面已经换到别的关键词时，前一个关键词的卡片不在当前页上。"""
    results = {"露营": [[note_id(1), note_id(2)]], "咖啡": [[note_id(3)]]}
    site, ctx = FakeSite(results), Context()
    fetcher = fetcher_for(site, fast_time)
    await search(fetcher, "露营", ctx)
    await search(fetcher, "咖啡", ctx)

    for number in (1, 2, 3):
        assert await collect(fetcher, note_id(number), ctx) == "结果页卡片"

    assert site.searches == ["露营", "咖啡", "露营", "咖啡"]
    assert site.direct == []


async def test_keywords_searched_one_at_a_time_never_go_back_to_results(
    fast_time: list[FakeSite],
) -> None:
    """执行器的顺序：搜一个采一个，换关键词不用回结果页。"""
    results = {"露营": [[note_id(1), note_id(2)]], "咖啡": [[note_id(3)]]}
    site, ctx = FakeSite(results), Context()
    fetcher = fetcher_for(site, fast_time)

    await search(fetcher, "露营", ctx)
    for number in (1, 2):
        assert await collect(fetcher, note_id(number), ctx) == "结果页卡片"
    await search(fetcher, "咖啡", ctx)
    assert await collect(fetcher, note_id(3), ctx) == "结果页卡片"

    assert site.searches == ["露营", "咖啡"]
    assert site.direct == []


async def test_notes_outside_this_search_open_directly_without_searching(
    fast_time: list[FakeSite],
) -> None:
    """指定内容和续跑：这个取数器没搜到过它，没有结果页可回。"""
    site, ctx = FakeSite(one_page(1)), Context()
    fetcher = fetcher_for(site, fast_time)

    assert await collect(fetcher, note_id(9), ctx) == "直接打开：不是本次搜索的结果"

    assert site.searches == [] and site.direct == [note_id(9)]


async def test_stops_returning_to_results_that_keep_failing(fast_time: list[FakeSite]) -> None:
    """回结果页本身也是一次导航；总找不到时不能每条都多开一页。"""
    site, ctx = FakeSite(one_page(1, 2, 3, 4, 5)), Context()
    site.hidden.update(note_id(number) for number in (1, 2, 3, 4, 5))
    fetcher = fetcher_for(site, fast_time)
    await search(fetcher, "露营", ctx)

    routes = [await collect(fetcher, note_id(number), ctx) for number in (1, 2, 3, 4, 5)]

    assert routes[:3] == [NOT_FOUND] * 3
    assert routes[3:] == ["直接打开：回结果页的次数已用完"] * 2
    assert len(site.searches) == 3 and len(site.direct) == 5


async def test_results_that_will_not_reopen_fall_back_to_a_direct_open(
    fast_time: list[FakeSite],
) -> None:
    site, ctx = FakeSite(one_page(1, 2)), Context()
    site.hidden.add(note_id(1))
    fetcher = fetcher_for(site, fast_time)
    await search(fetcher, "露营", ctx)
    await collect(fetcher, note_id(1), ctx)
    site.broken_search = True

    assert await collect(fetcher, note_id(2), ctx) == "直接打开：结果页打不开"

    assert site.direct == [note_id(1), note_id(2)]


async def test_risk_while_looking_for_a_card_stops_at_once(fast_time: list[FakeSite]) -> None:
    site, ctx = FakeSite(three_pages()), Context()
    site.hidden.add(note_id(1))
    fetcher = fetcher_for(site, fast_time)
    await search(fetcher, "露营", ctx, pages=1)
    site.next_search_response = Response("/api/sns/web/v2/search/notes", {}, status=461)

    with pytest.raises(RiskDetected):
        await collect(fetcher, note_id(1), ctx)

    assert site.direct == [] and site.clicked == []


async def test_filter_panel_that_stays_closed_is_retried_like_a_network_error(
    fast_time: list[FakeSite],
) -> None:
    """悬停没展开面板，这不是页面改版，重新搜一次通常就好。"""
    site, ctx = FakeSite(one_page(1)), Context()
    site.stuck_filter = True
    fetcher = fetcher_for(site, fast_time)

    with pytest.raises(TransientError):
        await search(fetcher, "露营", ctx, sort="new")
