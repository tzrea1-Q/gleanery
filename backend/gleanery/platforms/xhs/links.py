"""小红书链接解析。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from gleanery.platforms.types import ContentRef

_ID = r"[0-9a-fA-F]{24}"
_URL = re.compile(
    r"(?<![\w.@/\-])(?:https?://)?(?:www\.)?xiaohongshu\.com(?=[/:?#\s]|$)[^\s]*", re.IGNORECASE
)


def parse_link(text: str) -> ContentRef | None:
    text = text.strip()
    ext: dict[str, str] = {}
    if re.fullmatch(_ID, text):
        note_id = text
    else:
        match = _URL.search(text)
        if match is None:
            return None
        candidate = match.group()
        try:
            url = urlsplit(candidate if "://" in candidate else "https://" + candidate)
            if url.hostname not in ("www.xiaohongshu.com", "xiaohongshu.com"):
                return None
            path = re.fullmatch(rf"/(?:explore|discovery/item)/({_ID})/?", url.path)
            if path is None:
                return None
            note_id = path.group(1)
            query = parse_qs(url.query, keep_blank_values=True)
            ext = {key: query[key][0] for key in ("xsec_token", "xsec_source") if key in query}
        except ValueError:
            return None
    return ContentRef(
        platform="xhs",
        platform_id=note_id,
        url=f"https://www.xiaohongshu.com/explore/{note_id}",
        ext=ext,
    )


def with_token(url: str, ext: dict[str, Any]) -> str:
    """笔记网址带上 `xsec_token`，网页和浏览器里才打得开；没有 token 时原样返回。"""
    token = ext.get("xsec_token")
    if not token:
        return url
    source = ext.get("xsec_source") or "pc_search"
    return (
        f"{url}?xsec_token={quote(str(token), safe='')}&xsec_source={quote(str(source), safe='')}"
    )
