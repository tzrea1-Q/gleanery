"""按平台分派链接解析与打开用的网址。"""

from __future__ import annotations

from typing import Any

from gleanery.platforms.bili import links as bili_links
from gleanery.platforms.types import ContentRef, Platform
from gleanery.platforms.xhs import links as xhs_links


def parse_link(platform: Platform, text: str) -> ContentRef | None:
    return (bili_links if platform == "bili" else xhs_links).parse_link(text)


def open_url(platform: Platform, url: str, ext: dict[str, Any]) -> str:
    """给用户点开的网址。小红书要带 token；Agent 的工具和视图只用不带 token 的 `url`。"""
    return xhs_links.with_token(url, ext) if platform == "xhs" else url
