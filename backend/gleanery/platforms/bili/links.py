import re
from urllib.parse import urlsplit

from gleanery.platforms.types import ContentRef

_ID = re.compile(r"(?:BV[0-9A-Za-z]{10}|av[0-9]+)")


def parse_link(text: str) -> ContentRef | None:
    text = text.strip()
    if _ID.fullmatch(text):
        video_id = text
    else:
        url = urlsplit(text if "://" in text else "https://" + text)
        if url.hostname not in ("www.bilibili.com", "bilibili.com", "m.bilibili.com"):
            return None
        match = re.fullmatch(r"/video/((?:BV[0-9A-Za-z]{10}|av[0-9]+))/?", url.path)
        if not match:
            return None
        video_id = match.group(1)
    return ContentRef(
        platform="bili", platform_id=video_id, url=f"https://www.bilibili.com/video/{video_id}"
    )
