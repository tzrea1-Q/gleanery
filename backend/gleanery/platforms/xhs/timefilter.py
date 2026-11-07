"""小红书搜索的时间筛选映射与卡片发布时间。"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Literal

from gleanery.platforms.types import TimeRange

XhsTimeFilter = Literal["day", "week", "half_year"]
# 2026-11-03 真站核对：发布时间筛选为"不限、一天内、一周内、半年内"，选中后写进搜索请求体的
# `filters`（`filter_note_time`）。页面没写明口径，按"距现在 N×24 小时"理解；半年取 180 天，
# 宁可少用一次筛选，也不让筛选漏掉范围内的内容（范围仍由执行器采后过滤保证）。
FILTER_SPANS: tuple[tuple[XhsTimeFilter, int], ...] = (("day", 1), ("week", 7), ("half_year", 180))
BEIJING = timezone(timedelta(hours=8))


def filter_option(
    time_range: TimeRange | None, now_ms: int, tz: tzinfo | None = None
) -> XhsTimeFilter | None:
    """能覆盖整个时间范围的最窄页面选项；覆盖不了返回 None。"""
    if time_range is None:
        return None
    today = datetime.fromtimestamp(now_ms / 1000, tz).date()
    if any(
        value is not None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None
        for value in (time_range.start, time_range.end)
    ):
        return None
    try:
        start = date.fromisoformat(time_range.start) if time_range.start is not None else None
        end = date.fromisoformat(time_range.end) if time_range.end is not None else None
        lower = today - timedelta(days=time_range.last_days - 1) if time_range.last_days else None
    except (ValueError, OverflowError):
        return None
    if start is not None:
        lower = max(lower, start) if lower is not None else start
    upper = min(today, end) if end is not None else today
    if lower is None or upper < lower:
        return None
    return next((option for option, days in FILTER_SPANS if (today - lower).days < days), None)


def publish_text_ms(text: str, captured_at: int) -> int | None:
    """卡片上的发布时间文字换成毫秒时间戳，按北京时间；认不出返回 None。"""
    text = text.strip().removeprefix("编辑于").strip()
    text = re.sub(r"\s+\S+$", "", text) if re.search(r"\s+[^\d\s]\S*$", text) else text
    captured = datetime.fromtimestamp(captured_at / 1000, BEIJING)
    if text == "刚刚":
        return captured_at
    relative = re.fullmatch(r"(\d+)(分钟|小时|天)前", text)
    if relative:
        unit = {"分钟": 60_000, "小时": 3_600_000, "天": 86_400_000}[relative[2]]
        return captured_at - int(relative[1]) * unit
    try:
        clock = re.fullmatch(r"(今天|昨天)\s+(\d{2}):(\d{2})", text)
        if clock:
            day = captured.date() - timedelta(days=clock[1] == "昨天")
            value = datetime.combine(day, time(int(clock[2]), int(clock[3])), BEIJING)
        elif re.fullmatch(r"\d{2}-\d{2}", text):
            month, day_number = map(int, text.split("-"))
            year = captured.year - ((month, day_number) > (captured.month, captured.day))
            value = datetime(year, month, day_number, tzinfo=BEIJING)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            value = datetime.combine(date.fromisoformat(text), time(), BEIJING)
        else:
            return None
        return int(value.timestamp() * 1000)
    except (ValueError, OverflowError):
        return None
