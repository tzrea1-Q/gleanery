import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gleanery.platforms.bili import selectors
from gleanery.platforms.bili.driver import pubtime_window
from gleanery.platforms.bili.parser import parse
from gleanery.platforms.types import Capture, TimeRange

TZ = timezone(timedelta(hours=8))
NOW = int(datetime(2026, 11, 2, 17, 30, tzinfo=TZ).timestamp() * 1000)


def seconds(*args: int) -> int:
    return int(datetime(*args, tzinfo=TZ).timestamp())


def test_last_days_matches_page_preset() -> None:
    # 页面"最近一周"在 11-02 给出的就是 10-27 0 点到 11-02 23:59:59。
    assert pubtime_window(TimeRange(last_days=7), NOW, TZ) == (
        seconds(2026, 10, 27),
        seconds(2026, 11, 2, 23, 59, 59),
    )
    assert pubtime_window(TimeRange(last_days=1), NOW, TZ) == (
        seconds(2026, 11, 2),
        seconds(2026, 11, 2, 23, 59, 59),
    )


def test_dates() -> None:
    assert pubtime_window(TimeRange(start="2026-09-01", end="2026-09-07"), NOW, TZ) == (
        seconds(2026, 9, 1),
        seconds(2026, 9, 7, 23, 59, 59),
    )
    # 只有起始日期时截到今天。
    assert pubtime_window(TimeRange(start="2026-10-01"), NOW, TZ) == (
        seconds(2026, 10, 1),
        seconds(2026, 11, 2, 23, 59, 59),
    )
    # 近 N 天与起止日期同时给出时取交集，和采后过滤一致。
    assert pubtime_window(TimeRange(last_days=30, start="2026-10-20"), NOW, TZ) == (
        seconds(2026, 10, 20),
        seconds(2026, 11, 2, 23, 59, 59),
    )


def test_unmapped_ranges_skip_filter() -> None:
    assert pubtime_window(None, NOW, TZ) is None
    assert pubtime_window(TimeRange(end="2026-10-01"), NOW, TZ) is None
    assert pubtime_window(TimeRange(start="2026/10/01"), NOW, TZ) is None


def test_recorded_filtered_search_stays_in_range() -> None:
    # 2026-11-02 真站点"最新发布、近 30 天"：接口带上筛选参数，结果都落在区间里。
    path = (
        Path(__file__).parents[2]
        / "fixtures/bili/x__web-interface__wbi__search__type/20261102-pubtime_30d.json"
    )
    source = Capture.model_validate(json.loads(path.read_text())["capture"])
    begin = int(source.query[selectors.PUBTIME_BEGIN]) * 1000
    end = int(source.query[selectors.PUBTIME_END]) * 1000
    assert end - begin > 29 * 86400 * 1000
    result = parse(source)
    assert result and result.search and result.search.contents
    for content in result.search.contents:
        assert content.published_at is not None and begin <= content.published_at <= end
