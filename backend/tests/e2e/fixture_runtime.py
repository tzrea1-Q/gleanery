"""e2e 用的平台运行时：不开浏览器，用录制的 B 站和小红书 fixture 回放搜索与内容页。

- 搜索任何关键词都返回该平台搜索 fixture 解析出的那一页；
- 打开任何内容都用同一组内容页 fixture 拼结果，内容 ID 换成请求的那条；
- B 站关键词里带"风控"时，打开第一条内容就抛风控信号，用来测风控暂停。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Literal

from gleanery.collect.runtime import RuntimeLoginPhase
from gleanery.platforms.bili import fetcher as bili_fetcher
from gleanery.platforms.bili import parser as bili_parser
from gleanery.platforms.errors import RiskDetected
from gleanery.platforms.types import (
    Capture,
    CollectResult,
    CommentRecord,
    ContentRef,
    Depth,
    FetchContext,
    Fetcher,
    ParsedCapture,
    Platform,
    ProbeResult,
    RiskVerdict,
    SearchPage,
    SortOrder,
    TimeRange,
)
from gleanery.platforms.xhs import fetcher as xhs_fetcher
from gleanery.platforms.xhs import parser as xhs_parser

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RISK_KEYWORD = "风控"
_RECORDED_ON: dict[Platform, str] = {"bili": "20261101", "xhs": "20261103"}
_SEARCH: dict[Platform, str] = {"bili": "ssr__search", "xhs": "search__notes"}
_CONTENT: dict[Platform, list[str]] = {
    "bili": ["ssr__video", "subtitle", "x__v2__reply__wbi__main", "x__v2__reply__reply"],
    "xhs": ["feed", "comment__page", "comment__sub__page"],
}


def _capture(platform: Platform, kind_dir: str, case: str = "normal") -> Capture:
    path = FIXTURES / platform / kind_dir / f"{_RECORDED_ON[platform]}-{case}.json"
    return Capture.model_validate(json.loads(path.read_text())["capture"])


def _parse(capture: Capture) -> ParsedCapture | None:
    return (bili_parser if capture.platform == "bili" else xhs_parser).parse(capture)


def _rekey(comment: CommentRecord, content_id: str) -> CommentRecord:
    # 评论 ID 全局唯一，回放同一组评论时按内容加前缀，免得多条内容抢同一批评论。
    return comment.model_copy(
        update={
            "platform_id": f"{content_id}-{comment.platform_id}",
            "root_platform_id": comment.root_platform_id
            and f"{content_id}-{comment.root_platform_id}",
            "parent_platform_id": comment.parent_platform_id
            and f"{content_id}-{comment.parent_platform_id}",
            "content_platform_id": content_id,
        }
    )


class FixtureFetcher:
    def __init__(self, platform: Platform) -> None:
        self.platform: Platform = platform
        self.risky = False

    async def probe(self, ctx: FetchContext) -> ProbeResult:
        return ProbeResult(logged_in=True)

    async def search(
        self, keyword: str, sort: SortOrder, time_range: TimeRange | None, ctx: FetchContext
    ) -> AsyncIterator[SearchPage]:
        self.risky = self.platform == "bili" and RISK_KEYWORD in keyword
        parsed = _parse(_capture(self.platform, _SEARCH[self.platform]))
        assert parsed is not None and parsed.search is not None
        yield parsed.search.model_copy(update={"has_more": False})

    async def collect_content(
        self, ref: ContentRef, depth: Depth, ctx: FetchContext
    ) -> CollectResult:
        if self.risky:
            raise RiskDetected(RiskVerdict(kind="risk", signal="http_412", signal_type="status"))
        captures = [_capture(self.platform, kind) for kind in _CONTENT[self.platform]]
        assemble = (bili_fetcher if self.platform == "bili" else xhs_fetcher).assemble
        result = assemble(ref, depth, captures)
        content = result.content.model_copy(update={"platform_id": ref.platform_id, "url": ref.url})
        comments = [_rekey(comment, ref.platform_id) for comment in result.comments]
        subtitles = [
            subtitle.model_copy(update={"content_platform_id": ref.platform_id})
            for subtitle in result.subtitles
        ]
        return result.model_copy(
            update={"content": content, "comments": comments, "subtitles": subtitles}
        )

    async def close(self) -> None:
        pass


class FixtureRuntime:
    platforms: frozenset[Platform] = frozenset({"bili", "xhs"})

    def __init__(self) -> None:
        self.fetchers: list[FixtureFetcher] = []

    def fetcher(self, platform: Platform) -> Fetcher:
        # 一个任务用一个取数器，搜索时记下的"风控"标记要带到同一任务的内容阶段。
        fetcher = FixtureFetcher(platform)
        self.fetchers.append(fetcher)
        return fetcher

    async def login(
        self, platform: Platform, callback: Callable[[RuntimeLoginPhase], None]
    ) -> bool:
        callback("waiting_scan")
        callback("verifying")
        callback("succeeded")
        return True

    async def warmup(self, platform: Platform, minutes: float) -> None:
        pass

    def browser_running(self, platform: Platform) -> bool:
        return False

    def browser_kind(self, platform: Platform) -> Literal["chrome", "edge", "chromium"] | None:
        return None

    async def close(self) -> None:
        pass
