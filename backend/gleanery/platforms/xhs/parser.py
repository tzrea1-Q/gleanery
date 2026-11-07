from __future__ import annotations

import re
from typing import Any

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
)
from gleanery.platforms.xhs.timefilter import publish_text_ms


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _number(value: Any) -> int | None:
    return (
        parse_count(value)[0]
        if isinstance(value, (str, int)) and not isinstance(value, bool)
        else None
    )


def _missing(report: ParseReport, name: str) -> None:
    report.missing_fields[name] = report.missing_fields.get(name, 0) + 1


def _snake(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower(): _snake(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_snake(item) for item in value]
    return value


def _author(value: Any, report: ParseReport) -> AuthorRecord | None:
    user = _dict(value)
    identifier = _text(user.get("user_id"))
    if not identifier:
        _missing(report, "author")
        return None
    return AuthorRecord(
        platform="xhs",
        platform_id=identifier,
        nickname=_text(user.get("nickname")) or _text(user.get("nick_name")),
        avatar_url=_text(user.get("avatar")) or _text(user.get("image")),
    )


def _names(value: Any, key: str) -> list[str]:
    return [name for item in _list(value) if (name := _text(_dict(item).get(key)))]


def _content(
    card: dict[str, Any],
    identifier: str | None,
    report: ParseReport,
    *,
    detail: bool,
    capture: Capture,
    token: Any = None,
) -> ContentRecord | None:
    title = _text(card.get("title" if detail else "display_title"))
    body = _text(card.get("desc")) if detail else None
    if not identifier or (detail and not (title or body)):
        report.skipped_missing_core += 1
        return None
    if not title:
        _missing(report, "title")
    source = _dict(card.get("interact_info"))
    raw = {
        name: source.get(key)
        for name, key in (
            ("likes", "liked_count"),
            ("favorites", "collected_count"),
            ("comments", "comment_count"),
            ("shares", "share_count" if detail else "shared_count"),
        )
    }
    if not detail and raw["shares"] is None:
        raw["shares"] = source.get("share_count")
    numbers: dict[str, int | None] = {}
    approx = False
    for name, value in raw.items():
        # 真站核对：互动数为 0 时接口给空串，页面上也不显示数字。
        number, rounded = (
            (0, False)
            if value == ""
            else parse_count(value)
            if isinstance(value, (str, int)) and not isinstance(value, bool)
            else (None, False)
        )
        numbers[name] = number
        approx |= rounded
        if number is None:
            _missing(report, name)
    if detail:
        published = _number(card.get("time"))
    else:
        tags = _list(card.get("corner_tag_info"))
        text = next(
            (
                _text(_dict(tag).get("text"))
                for tag in tags
                if _dict(tag).get("type") == "publish_time"
            ),
            None,
        )
        published = publish_text_ms(text, capture.captured_at) if text else None
    if published is None:
        _missing(report, "published_at")
    ext: dict[str, Any] = {"counts_raw": raw, "counts_approx": approx}
    if detail:
        streams = _dict(_dict(_dict(card.get("video")).get("media")).get("stream"))
        video_url = next(
            (
                url
                for key in sorted(streams)
                for item in _list(streams[key])
                if (url := _text(_dict(item).get("master_url")))
            ),
            None,
        )
        ext.update(
            image_urls=_names(card.get("image_list"), "url_default"),
            video_url=video_url,
            at_users=_names(card.get("at_user_list"), "nickname"),
            ip_location=_text(card.get("ip_location")),
            published_approx=False,
        )
    else:
        ext.update(xsec_token=token, xsec_source="pc_search")
        if published is not None:
            ext["published_approx"] = True
    return ContentRecord(
        platform="xhs",
        platform_id=identifier,
        url=f"https://www.xiaohongshu.com/explore/{identifier}",
        kind="video" if card.get("type") == "video" else "image_text",
        title=title,
        body=body,
        author=_author(card.get("user"), report),
        published_at=published,
        platform_updated_at=_number(card.get("last_update_time")) if detail else None,
        counts=Counts(**numbers),
        tags=_names(card.get("tag_list"), "name") if detail else [],
        completeness="detail" if detail else "summary",
        ext=ext,
    )


def _comments(data: dict[str, Any], capture: Capture, report: ParseReport) -> CommentPage:
    entries = _list(data.get("comments"))
    report.nonempty_response = bool(entries)
    result: list[CommentRecord] = []

    def add(value: Any, root: str | None) -> None:
        item = _dict(value)
        identifier = _text(item.get("id"))
        content_id = _text(item.get("note_id")) or _text(capture.query.get("note_id"))
        if not identifier or not content_id:
            report.skipped_missing_core += 1
        else:
            body = _text(item.get("content"))
            if body is None:
                _missing(report, "body")
            published = _number(item.get("create_time"))
            likes = _number(item.get("like_count"))
            reply_count = _number(item.get("sub_comment_count")) if root is None else None
            for key, number in (("published_at", published), ("likes", likes)):
                if number is None:
                    _missing(report, key)
            if root is None and reply_count is None:
                _missing(report, "reply_count")
            result.append(
                CommentRecord(
                    platform="xhs",
                    platform_id=identifier,
                    content_platform_id=content_id,
                    root_platform_id=root,
                    parent_platform_id=(_text(_dict(item.get("target_comment")).get("id")) or root)
                    if root
                    else None,
                    author=_author(item.get("user_info"), report),
                    body=body or "",
                    published_at=published,
                    likes=likes,
                    reply_count=reply_count,
                    ip_location=_text(item.get("ip_location")),
                    ext={
                        "at_users": _names(item.get("at_users"), "nickname"),
                        "pictures": len(_list(item.get("pictures"))),
                        "show_tags": _list(item.get("show_tags")),
                    },
                )
            )
        if capture.kind == "comment/page":
            for child in _list(item.get("sub_comments")):
                add(child, identifier)

    root = (
        _text(capture.query.get("root_comment_id")) if capture.kind == "comment/sub/page" else None
    )
    for entry in entries:
        add(entry, root)
    report.items = len(result)
    return CommentPage(comments=result, has_more=data.get("has_more") is True, report=report)


def parse(capture: Capture) -> ParsedCapture | None:
    if capture.platform != "xhs" or capture.kind not in (
        "search/notes",
        "feed",
        "ssr:note",
        "comment/page",
        "comment/sub/page",
    ):
        return None
    body = _dict(capture.body)
    if (
        capture.status != 200
        or not body
        or body.get("code", 0) != 0
        or body.get("success") is False
    ):
        return ParsedCapture()
    if capture.kind != "ssr:note" and not isinstance(body.get("data"), dict):
        return ParsedCapture()
    data = _dict(body.get("data"))
    report = ParseReport()
    if capture.kind == "search/notes":
        entries = [
            item for item in _list(data.get("items")) if _dict(item).get("model_type") == "note"
        ]
        report.nonempty_response = bool(entries)
        contents = [
            content
            for item in entries
            if (
                content := _content(
                    _dict(_dict(item).get("note_card")),
                    _text(_dict(item).get("id")),
                    report,
                    detail=False,
                    capture=capture,
                    token=_dict(item).get("xsec_token"),
                )
            )
            is not None
        ]
        report.items = len(contents)
        return ParsedCapture(
            search=SearchPage(
                contents=contents, has_more=data.get("has_more") is True, report=report
            ),
            report=report,
        )
    if capture.kind in ("feed", "ssr:note"):
        if capture.kind == "feed":
            items = _list(data.get("items"))
            card = _dict(_dict(items[0]).get("note_card")) if items else {}
            identifier = _text(card.get("note_id")) or (
                _text(_dict(items[0]).get("id")) if items else None
            )
        else:
            card = _dict(_snake(body.get("note")))
            identifier = _text(card.get("note_id")) or _text(body.get("note_id"))
        report.nonempty_response = bool(card)
        content = _content(card, identifier, report, detail=True, capture=capture) if card else None
        report.items = int(content is not None)
        return ParsedCapture(content=content, report=report)
    comments = _comments(data, capture, report)
    return ParsedCapture(comments=comments, report=report)
