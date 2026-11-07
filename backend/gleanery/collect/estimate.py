"""预计耗时：按经验值估算，显示在计划卡片与进度上，Agent 不自己估。

经验值来自真实页面的录制：两个平台搜索每页约 20 条可用结果；B 站评论每页 20 条、
楼中楼每页 10 条，小红书评论每页 10 条、每点一次"展开"5 条；约三成一级评论带回复；
打开内容页另有约 3 秒加载。
"""

from __future__ import annotations

import math
from typing import NamedTuple

from gleanery.collect.plan import PlatformSection
from gleanery.collect.types import RateLimits
from gleanery.platforms.types import Platform


class Experience(NamedTuple):
    search_per_page: int
    comments_per_page: int
    sub_comments_per_page: int
    """B 站楼中楼每页条数；小红书是每点一次"展开"加载的条数。"""
    roots_with_replies: float
    page_load_seconds: float


EXPERIENCE: dict[Platform, Experience] = {
    "bili": Experience(20, 20, 10, 0.3, 3.0),
    "xhs": Experience(20, 10, 5, 0.3, 3.0),
}


def _mean(bounds: tuple[float, float]) -> float:
    return (bounds[0] + bounds[1]) / 2


def content_seconds(section: PlatformSection, limits: RateLimits) -> float:
    """处理一条内容的预计秒数。只要摘要时为 0。"""
    depth = section.depth
    if not depth.opens_page:
        return 0.0
    experience = EXPERIENCE[section.platform]
    seconds = _mean(limits.page_interval) + experience.page_load_seconds
    comment_wait = _mean(limits.comment_page_interval)
    if depth.comments > 0:
        seconds += math.ceil(depth.comments / experience.comments_per_page) * comment_wait
        if depth.sub_comments and depth.sub_comments_per_root > 0:
            pages = math.ceil(depth.sub_comments_per_root / experience.sub_comments_per_page)
            seconds += depth.comments * experience.roots_with_replies * pages * comment_wait
    return seconds


def estimate_task_seconds(section: PlatformSection, limits: RateLimits) -> int:
    """一个平台分段的预计总秒数：搜索翻页 + 逐条内容 + 长休息。"""
    items = section.quantity + len(section.targets)
    search_pages = (
        math.ceil(section.quantity / EXPERIENCE[section.platform].search_per_page)
        if section.keywords
        else 0
    )
    seconds = search_pages * _mean(limits.page_interval)
    seconds += items * content_seconds(section, limits)
    seconds += (items // limits.long_rest_every) * _mean(limits.long_rest)
    return round(seconds)


def remaining_seconds(
    section: PlatformSection, limits: RateLimits, pending_items: int, searching: bool
) -> int:
    """进度里的预计剩余时间。搜索阶段没跑完时按整份分段估。"""
    if searching:
        return estimate_task_seconds(section, limits)
    seconds = pending_items * content_seconds(section, limits)
    seconds += (pending_items // limits.long_rest_every) * _mean(limits.long_rest)
    return round(seconds)
