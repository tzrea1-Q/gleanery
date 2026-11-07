from datetime import UTC, datetime, timedelta, timezone

import pytest

from gleanery.platforms.types import TimeRange
from gleanery.platforms.xhs.timefilter import filter_option, publish_text_ms

BEIJING = timezone(timedelta(hours=8))
NOW = int(datetime(2024, 3, 1, 12, tzinfo=BEIJING).timestamp() * 1000)


@pytest.mark.parametrize(
    ("bounds", "expected"),
    [
        ({"last_days": 1}, "day"),
        ({"last_days": 7}, "week"),
        ({"last_days": 8}, "half_year"),
        ({"last_days": 180}, "half_year"),
        ({"last_days": 181}, None),
        ({"start": "2024-02-28", "end": "2024-02-29"}, "week"),
        ({"last_days": 30, "start": "2024-03-01"}, "day"),
        ({"end": "2024-03-01"}, None),
        ({"start": "bad"}, None),
        ({"start": "20240301"}, None),
        ({"start": "2024-03-01", "end": "2024-02-29"}, None),
        ({"start": "2024-03-02"}, None),
    ],
)
def test_filter(bounds: dict[str, object], expected: str | None) -> None:
    assert filter_option(TimeRange.model_validate(bounds), NOW, BEIJING) == expected


def test_filter_uses_local_day() -> None:
    assert filter_option(TimeRange(start="2024-03-01"), NOW, UTC) == "day"
    assert filter_option(TimeRange(start="2024-03-01"), NOW, timezone(timedelta(hours=-12))) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (" 刚刚 ", NOW),
        ("编辑于 3分钟前 广东", NOW - 180_000),
        ("2小时前", NOW - 7_200_000),
        ("3天前 广东", NOW - 259_200_000),
        ("今天 08:30 北京", int(datetime(2024, 3, 1, 8, 30, tzinfo=BEIJING).timestamp() * 1000)),
        ("昨天 23:30", int(datetime(2024, 2, 29, 23, 30, tzinfo=BEIJING).timestamp() * 1000)),
        ("12-31", int(datetime(2023, 12, 31, tzinfo=BEIJING).timestamp() * 1000)),
        ("02-29", int(datetime(2024, 2, 29, tzinfo=BEIJING).timestamp() * 1000)),
        ("2020-02-29", int(datetime(2020, 2, 29, tzinfo=BEIJING).timestamp() * 1000)),
        ("02-30", None),
        ("今天 25:00", None),
        ("未知", None),
    ],
)
def test_publish_text(text: str, expected: int | None) -> None:
    assert publish_text_ms(text, NOW) == expected
