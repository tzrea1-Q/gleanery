import json
from pathlib import Path

import pytest

from gleanery.platforms.types import Capture, ParsedCapture
from gleanery.platforms.xhs.parser import parse
from gleanery.platforms.xhs.timefilter import publish_text_ms

ROOT = Path(__file__).parents[2] / "fixtures" / "xhs"
FIXTURES = sorted(path for path in ROOT.rglob("*.json") if not path.name.endswith(".expected.json"))


def capture(kind: str, case: str = "normal") -> Capture:
    return Capture.model_validate(
        json.loads((ROOT / kind / f"20261103-{case}.json").read_text())["capture"]
    )


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_fixture_snapshot(path: Path) -> None:
    source = Capture.model_validate(json.loads(path.read_text())["capture"])
    result = parse(source)
    assert (result.model_dump(mode="json", by_alias=True) if result else None) == json.loads(
        path.with_suffix(".expected.json").read_text()
    )


def test_search_fixtures() -> None:
    for case in ("normal", "sort_new_week", "last_page"):
        source = capture("search__notes", case)
        result = parse(source)
        assert result and result.search
        entries = [
            item for item in source.body["data"]["items"] if item.get("model_type") == "note"
        ]
        assert len(result.search.contents) == len(entries)
        assert result.search.has_more == source.body["data"]["has_more"]
        item = result.search.contents[0]
        card = entries[0]["note_card"]
        assert item.platform_id == entries[0]["id"] and item.title == card["display_title"]
        assert (
            item.ext["xsec_token"] == entries[0]["xsec_token"]
            and item.ext["xsec_source"] == "pc_search"
        )
        assert item.counts.likes == int(card["interact_info"]["liked_count"])
        tag = next(
            (tag for tag in card.get("corner_tag_info", []) if tag["type"] == "publish_time"), None
        )
        if tag:
            assert item.published_at == publish_text_ms(tag["text"], source.captured_at)
            assert item.ext["published_approx"] is True
    source = capture("search__notes")
    source.body["data"]["items"] = [{"model_type": "hot_query"}, {"model_type": "rec_query"}]
    result = parse(source)
    assert (
        result
        and result.search
        and not result.search.contents
        and not result.report.nonempty_response
    )
    source.body["data"]["items"] = [
        {
            "model_type": "note",
            "id": "abc",
            "note_card": {"interact_info": {"liked_count": "1.2万"}},
        }
    ]
    result = parse(source)
    assert result and result.search
    item = result.search.contents[0]
    assert item.title is None and item.counts.likes == 12000 and item.ext["counts_approx"]
    assert (
        result.report.missing_fields["title"] == 1
        and result.report.missing_fields["published_at"] == 1
    )
    source.body["data"]["items"][0]["id"] = ""
    result = parse(source)
    assert result and result.report.nonempty_response and result.report.skipped_missing_core == 1


def test_detail_fixtures() -> None:
    for kind, cases in (
        ("feed", ("normal", "video")),
        ("ssr__note", ("normal", "guest", "no_comments")),
    ):
        for case in cases:
            source = capture(kind, case)
            result = parse(source)
            assert result and result.content
            item = result.content
            assert item.platform_id and item.url.endswith(item.platform_id) and item.body
            assert item.kind == ("video" if case == "video" else "image_text")
            assert item.ext["published_approx"] is False and item.ext["image_urls"]
            assert item.ext["counts_raw"] and "at_users" in item.ext and "ip_location" in item.ext
            assert bool(item.ext["video_url"]) == (case == "video")
            assert item.published_at and item.platform_updated_at
    source = capture("feed")
    card = source.body["data"]["items"][0]["note_card"]
    card["title"] = ""
    result = parse(source)
    assert (
        result
        and result.content
        and result.content.title is None
        and result.report.missing_fields["title"] == 1
    )
    card["desc"] = ""
    result = parse(source)
    assert result and result.content is None and result.report.skipped_missing_core == 1


def test_blank_counts_are_zero() -> None:
    source = capture("feed")
    card = source.body["data"]["items"][0]["note_card"]
    card["interact_info"].update(liked_count="", collected_count="", comment_count="")
    card["interact_info"].pop("share_count")
    result = parse(source)
    assert result and result.content
    counts = result.content.counts
    assert (counts.likes, counts.favorites, counts.comments, counts.shares) == (0, 0, 0, None)
    assert result.report.missing_fields == {"shares": 1}


def test_detail_shapes_match() -> None:
    feed = capture("feed")
    feed.body["data"]["items"] = [
        {
            "note_card": {
                "note_id": "id",
                "type": "normal",
                "title": "标题",
                "desc": "正文",
                "user": {"user_id": "u", "nickname": "名", "avatar": "a"},
                "time": 123,
                "last_update_time": 456,
                "interact_info": {
                    "liked_count": "1",
                    "collected_count": "2",
                    "comment_count": "3",
                    "share_count": "4",
                },
                "image_list": [{"url_default": "image"}],
                "tag_list": [{"name": "标签"}],
                "at_user_list": [{"nickname": "人"}],
                "ip_location": "北京",
            }
        }
    ]
    ssr = capture("ssr__note")
    ssr.body = {
        "note_id": "id",
        "note": {
            "noteId": "id",
            "type": "normal",
            "title": "标题",
            "desc": "正文",
            "user": {"userId": "u", "nickname": "名", "avatar": "a"},
            "time": 123,
            "lastUpdateTime": 456,
            "interactInfo": {
                "likedCount": "1",
                "collectedCount": "2",
                "commentCount": "3",
                "shareCount": "4",
            },
            "imageList": [{"urlDefault": "image"}],
            "tagList": [{"name": "标签"}],
            "atUserList": [{"nickname": "人"}],
            "ipLocation": "北京",
        },
    }
    a, b = parse(feed), parse(ssr)
    assert a and b and a.content and a.content == b.content


def test_comment_fixtures() -> None:
    for kind, cases in (
        ("comment__page", ("normal", "last_page", "guest")),
        ("comment__sub__page", ("normal", "last_page")),
    ):
        for case in cases:
            source = capture(kind, case)
            result = parse(source)
            assert result and result.comments
            entries = source.body["data"]["comments"]
            expected = (
                sum(1 + len(item.get("sub_comments", [])) for item in entries)
                if kind == "comment__page"
                else len(entries)
            )
            assert len(result.comments.comments) == expected
            assert result.comments.has_more == source.body["data"]["has_more"]
            first = result.comments.comments[0]
            assert first.platform_id == entries[0]["id"] and first.body == entries[0]["content"]
            assert first.likes == int(entries[0]["like_count"])
            if kind == "comment__sub__page":
                assert first.root_platform_id == source.query["root_comment_id"]
                assert first.parent_platform_id == entries[0]["target_comment"]["id"]
            elif entries[0].get("sub_comments"):
                child = result.comments.comments[1]
                assert child.root_platform_id == first.platform_id
                assert (
                    child.parent_platform_id
                    == entries[0]["sub_comments"][0]["target_comment"]["id"]
                )
    source = capture("comment__page")
    source.body["data"]["comments"] = [
        {
            "id": "c",
            "note_id": "n",
            "content": "",
            "pictures": [{}, {}],
            "sub_comments": [{"id": "child", "note_id": "n", "content": "回复"}],
        }
    ]
    result = parse(source)
    assert result and result.comments
    first, child = result.comments.comments
    assert (
        first.body == ""
        and first.ext["pictures"] == 2
        and result.report.missing_fields["body"] == 1
    )
    assert child.root_platform_id == "c" and child.parent_platform_id == "c"


@pytest.mark.parametrize("kind", ["search__notes", "comment__page", "comment__sub__page"])
def test_empty_pages(kind: str) -> None:
    result = parse(capture(kind, "empty"))
    assert result and result.report.items == 0 and not result.report.nonempty_response


def test_empty_feed_errors_and_unknown() -> None:
    result = parse(capture("feed", "empty"))
    assert result and result.content is None and not result.report.nonempty_response
    for kind, cases in (
        ("search__notes", ("guest", "risk", "risk_ip")),
        ("feed", ("guest", "risk")),
        ("comment__page", ("login_lost", "risk")),
        ("comment__sub__page", ("guest", "risk")),
    ):
        for case in cases:
            assert parse(capture(kind, case)) == ParsedCapture()
    source = capture("feed")
    source.kind = "unknown"
    assert parse(source) is None
    source.platform = "bili"
    source.kind = "feed"
    assert parse(source) is None
