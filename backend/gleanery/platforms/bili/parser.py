from __future__ import annotations

import html
import re
from typing import Any

from pydantic import ValidationError

from gleanery.platforms.normalize import parse_count
from gleanery.platforms.types import (
    AuthorRecord,
    Capture,
    CommentPage,
    CommentRecord,
    ContentRecord,
    Counts,
    ParsedCapture,
    ParseReport,
    SearchPage,
    SubtitleRecord,
    SubtitleSegment,
)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _id(value: Any) -> str | None:
    return (
        str(value)
        if isinstance(value, (str, int))
        and not isinstance(value, bool)
        and value not in ("", 0, "0")
        else None
    )


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _missing(report: ParseReport, name: str) -> None:
    report.missing_fields[name] = report.missing_fields.get(name, 0) + 1


def _number(value: Any) -> int | None:
    return (
        parse_count(value)[0]
        if isinstance(value, (str, int)) and not isinstance(value, bool)
        else None
    )


def _timestamp(value: Any, report: ParseReport) -> int | None:
    number = _number(value)
    if number is None:
        _missing(report, "published_at")
    return number * 1000 if number is not None else None


def _author(mid: Any, name: Any, avatar: Any, report: ParseReport) -> AuthorRecord | None:
    identifier = _id(mid)
    if identifier is None:
        _missing(report, "author")
        return None
    return AuthorRecord(
        platform="bili", platform_id=identifier, nickname=_text(name), avatar_url=_text(avatar)
    )


def _duration(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value >= 0 else None
    if isinstance(value, str) and re.fullmatch(r"\d+(?::\d+){1,2}", value):
        total = 0
        for part in value.split(":"):
            total = total * 60 + int(part)
        return total
    return None


def _tags(value: Any) -> list[str]:
    """搜索结果的 `tag` 是逗号分隔的标签串；视频页 SSR 不带标签。"""
    if not isinstance(value, str):
        return []
    return list(dict.fromkeys(tag.strip() for tag in value.split(",") if tag.strip()))


def _content(data: dict[str, Any], report: ParseReport, *, detail: bool) -> ContentRecord | None:
    identifier = _id(data.get("bvid"))
    title = _text(data.get("title"))
    if title and not detail:
        title = _text(html.unescape(re.sub(r"<[^>]*>", "", title)))
    body = _text(data.get("desc") if detail else data.get("description"))
    if not identifier or not (title or body):
        report.skipped_missing_core += 1
        return None
    owner = _dict(data.get("owner")) if detail else data
    author = _author(
        owner.get("mid"),
        owner.get("name" if detail else "author"),
        owner.get("face" if detail else "upic"),
        report,
    )
    source = _dict(data.get("stat")) if detail else data
    keys = {
        "likes": "like",
        "favorites": "favorite" if detail else "favorites",
        "comments": "reply" if detail else "review",
        "shares": "share",
        "plays": "view" if detail else "play",
        "coins": "coin",
        "danmaku": "danmaku" if detail else "video_review",
    }
    raw = {name: source.get(key) for name, key in keys.items()}
    numbers: dict[str, int | None] = {}
    approx = False
    for name, value in raw.items():
        number, rounded = (
            parse_count(value)
            if isinstance(value, (str, int)) and not isinstance(value, bool)
            else (None, False)
        )
        numbers[name] = number
        approx |= rounded
        # 搜索结果本来就不给分享数和投币数，不算缺失。
        if number is None and (detail or name not in ("shares", "coins")):
            _missing(report, name)
    duration = _duration(data.get("duration"))
    if duration is None:
        _missing(report, "duration")
    ext = {key: data[key] for key in ("aid", "cid", "pic", "tid", "tid_v2") if key in data}
    # 视频页 SSR 的 tname、tname_v2 都是空串（2026-11-02 冒烟库 92 条视频页无一例外），只剩
    # tid、tid_v2；分区名只有搜索结果的 typename 给。取不到就不写，入库合并时保留搜索阶段的值。
    if detail:
        category = _text(data.get("tname")) or _text(data.get("tname_v2"))
    else:
        category = _text(data.get("typename"))
    if category:
        ext["tname"] = category
    ext.update(
        duration=duration,
        coins=numbers["coins"],
        danmaku=numbers["danmaku"],
        counts_raw=raw,
        counts_approx=approx,
    )
    return ContentRecord(
        platform="bili",
        platform_id=identifier,
        url=f"https://www.bilibili.com/video/{identifier}",
        kind="video",
        title=title,
        body=body,
        author=author,
        published_at=_timestamp(data.get("pubdate"), report),
        counts=Counts(
            **{key: numbers[key] for key in ("likes", "favorites", "comments", "shares", "plays")}
        ),
        tags=[] if detail else _tags(data.get("tag")),
        completeness="detail" if detail else "summary",
        ext=ext,
    )


def _comments(data: dict[str, Any], capture: Capture, report: ParseReport) -> CommentPage:
    roots = data.get("replies")
    tops = data.get("top_replies")
    roots = roots if isinstance(roots, list) else []
    tops = tops if isinstance(tops, list) else []
    report.nonempty_response = bool(roots or tops)
    result: list[CommentRecord] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        item = _dict(value)
        identifier = _id(item.get("rpid_str")) or _id(item.get("rpid"))
        if identifier and identifier in seen:
            children = item.get("replies")
            if isinstance(children, list):
                for child in children:
                    add(child)
            return
        if identifier:
            seen.add(identifier)
        body = _text(_dict(item.get("content")).get("message"))
        oid = _id(item.get("oid")) or _id(capture.query.get("oid"))
        if not identifier or not body or not oid:
            report.skipped_missing_core += 1
        else:
            member = _dict(item.get("member"))
            likes = _number(item.get("like"))
            reply_count = _number(item.get("rcount"))
            for key, number in (("likes", likes), ("reply_count", reply_count)):
                if number is None:
                    _missing(report, key)
            location = _text(_dict(item.get("reply_control")).get("location"))
            result.append(
                CommentRecord(
                    platform="bili",
                    platform_id=identifier,
                    content_platform_id=oid,
                    root_platform_id=_id(item.get("root_str")) or _id(item.get("root")),
                    parent_platform_id=_id(item.get("parent_str")) or _id(item.get("parent")),
                    author=_author(
                        member.get("mid"), member.get("uname"), member.get("avatar"), report
                    ),
                    body=body,
                    published_at=_timestamp(item.get("ctime"), report),
                    likes=likes,
                    reply_count=reply_count,
                    ip_location=location.removeprefix("IP属地：") if location else None,
                )
            )
        children = item.get("replies")
        if isinstance(children, list):
            for child in children:
                add(child)

    for item in tops + roots:
        add(item)
    report.items = len(result)
    if capture.kind.endswith("/main"):
        has_more = not bool(_dict(data.get("cursor")).get("is_end", True))
    else:
        page = _dict(data.get("page"))
        num, size, count = (_number(page.get(key)) for key in ("num", "size", "count"))
        has_more = num is not None and size is not None and count is not None and num * size < count
    return CommentPage(comments=result, has_more=has_more, report=report)


def parse(capture: Capture) -> ParsedCapture | None:
    if capture.platform != "bili":
        return None
    report = ParseReport()
    if capture.kind == "subtitle":
        data = _dict(capture.body)
        body = data.get("body")
        if capture.status != 200 or not isinstance(body, dict):
            _missing(report, "subtitles")
            return ParsedCapture(report=report)
        track = _dict(data.get("track"))
        identifier, part, lang = (
            _id(data.get("bvid")),
            _id(data.get("cid")),
            _text(track.get("lan")),
        )
        if not identifier or not part or not lang:
            report.skipped_missing_core += 1
            return ParsedCapture(report=report)
        segments = []
        for segment in body.get("body", []) if isinstance(body.get("body"), list) else []:
            try:
                segments.append(SubtitleSegment.model_validate(segment))
            except ValidationError:
                _missing(report, "segments")
        report.items = 1
        subtitle = SubtitleRecord(
            content_platform_id=identifier,
            part_id=part,
            part_title=_text(data.get("part")),
            lang=lang,
            ai_generated=bool(track.get("ai_type")) or lang.startswith("ai-"),
            segments=segments,
        )
        return ParsedCapture(subtitles=[subtitle], report=report)
    if (
        capture.status != 200
        or not isinstance(capture.body, dict)
        or capture.body.get("code", 0) != 0
    ):
        return None
    if capture.kind in ("ssr:search", "x/web-interface/wbi/search/type"):
        data = capture.body if capture.kind == "ssr:search" else _dict(capture.body.get("data"))
        entries = data.get("result")
        entries = entries if isinstance(entries, list) else []
        videos = [
            item for item in entries if not isinstance(item, dict) or item.get("type") == "video"
        ]
        # 只看视频条目：全是用户卡片、直播卡片的页解析出 0 条不算页面改版。
        report.nonempty_response = bool(videos)
        contents = [
            content
            for item in videos
            if (content := _content(_dict(item), report, detail=False)) is not None
        ]
        report.items = len(contents)
        page, pages = _number(data.get("page")), _number(data.get("numPages"))
        search = SearchPage(
            contents=contents,
            has_more=page is not None and pages is not None and page < pages,
            report=report,
        )
        return ParsedCapture(search=search, report=report)
    if capture.kind == "ssr:video":
        report.nonempty_response = bool(capture.body)
        content = _content(capture.body, report, detail=True)
        report.items = int(content is not None)
        return ParsedCapture(content=content, report=report)
    if capture.kind in ("x/v2/reply/wbi/main", "x/v2/reply/reply"):
        comments = _comments(_dict(capture.body.get("data")), capture, report)
        return ParsedCapture(comments=comments, report=report)
    return None
