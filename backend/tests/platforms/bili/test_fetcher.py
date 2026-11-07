import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import pytest

from gleanery.platforms.bili import selectors
from gleanery.platforms.bili.fetcher import BiliFetcher, assemble
from gleanery.platforms.errors import PageChanged
from gleanery.platforms.types import Capture, ContentRef, Depth, FetchContext
from tests.platforms.bili.test_driver_fake_page import Context, FakePage, Response

FIXTURES = Path(__file__).parents[2] / "fixtures" / "bili"
REF = ContentRef(
    platform="bili", platform_id="BV1qxmbYvEbY", url="https://www.bilibili.com/video/BV1qxmbYvEbY"
)


def capture(kind_dir: str, case: str) -> Capture:
    data = json.loads((FIXTURES / kind_dir / f"20261101-{case}.json").read_text())
    return Capture.model_validate(data["capture"])


def captures() -> list[Capture]:
    # 同一视频一次打开的截获顺序：播放器、视频 SSR、字幕、一级评论、楼中楼。
    return [
        capture("x__player__wbi__v2", "with_subtitle"),
        capture("ssr__video", "normal"),
        capture("subtitle", "normal"),
        capture("x__v2__reply__wbi__main", "normal"),
        capture("x__v2__reply__reply", "normal"),
    ]


def test_assemble_full_depth() -> None:
    depth = Depth(comments=100, sub_comments=True, sub_comments_per_root=10, subtitles=True)
    result = assemble(REF, depth, captures())
    assert result.content.platform_id == "BV1qxmbYvEbY"
    assert result.content.completeness == "detail"
    assert {comment.content_platform_id for comment in result.comments} == {"BV1qxmbYvEbY"}
    ids = [comment.platform_id for comment in result.comments]
    assert len(ids) == len(set(ids))
    roots = [comment for comment in result.comments if comment.root_platform_id is None]
    kept = {root.platform_id for root in roots}
    assert all(
        comment.root_platform_id in kept
        for comment in result.comments
        if comment.root_platform_id is not None
    )
    assert len(result.subtitles) == 1 and result.subtitles[0].content_platform_id == "BV1qxmbYvEbY"
    assert result.report.items > 0


def test_assemble_caps_roots_and_sub_comments() -> None:
    depth = Depth(comments=1, sub_comments=True, sub_comments_per_root=2, subtitles=False)
    result = assemble(REF, depth, captures())
    roots = [comment for comment in result.comments if comment.root_platform_id is None]
    assert len(roots) == 1
    children = [comment for comment in result.comments if comment.root_platform_id is not None]
    assert 0 < len(children) <= 2
    assert all(comment.root_platform_id == roots[0].platform_id for comment in children)
    assert result.subtitles == []


def test_assemble_without_sub_comments() -> None:
    result = assemble(REF, Depth(comments=100, sub_comments=False), captures())
    assert all(comment.root_platform_id is None for comment in result.comments)


def test_assemble_requires_video_ssr() -> None:
    with pytest.raises(PageChanged, match="missing_ssr"):
        assemble(REF, Depth(comments=20), captures()[2:])


class FakeManager:
    def __init__(self, page) -> None:
        self.page_instance = page
        self.opened = 0
        self.closed = 0

    @asynccontextmanager
    async def page(self, platform):
        self.opened += 1
        try:
            yield self.page_instance
        finally:
            self.closed += 1


@pytest.mark.parametrize("logged_in", [True, False])
async def test_probe(logged_in: bool) -> None:
    class NavPage(FakePage):
        async def goto(self, url: str, *, wait_until: str) -> None:
            self.url = url
            self.callback(Response(selectors.NAV, {"code": 0, "data": {"isLogin": logged_in}}))

    manager = FakeManager(NavPage())
    fetcher = BiliFetcher(cast(Any, manager))
    result = await fetcher.probe(cast(FetchContext, Context()))
    assert result.logged_in is logged_in
    assert manager.opened == 1 and manager.closed == 0
    await fetcher.close()
    assert manager.closed == 1
