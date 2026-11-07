import json
from pathlib import Path

import pytest

from gleanery.platforms.bili.parser import parse
from gleanery.platforms.registry import parser_for
from gleanery.platforms.types import Capture

ROOT = Path(__file__).parents[2] / "fixtures" / "bili"
FIXTURES = sorted(path for path in ROOT.rglob("*.json") if not path.name.endswith(".expected.json"))


def capture(kind: str, case: str = "normal") -> Capture:
    path = ROOT / kind / f"20261101-{case}.json"
    return Capture.model_validate(json.loads(path.read_text())["capture"])


@pytest.mark.parametrize("path", FIXTURES, ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_fixture_snapshot(path: Path) -> None:
    source = Capture.model_validate(json.loads(path.read_text())["capture"])
    result = parse(source)
    expected = json.loads(path.with_suffix(".expected.json").read_text())
    assert (result.model_dump(mode="json", by_alias=True) if result else None) == expected


def test_search_title_counts_and_last_page() -> None:
    source = capture("ssr__search")
    item = source.body["result"][0]
    item.update(title='<em class="keyword">茶 &amp; 饭</em>', duration="64:0", play="1.2万")
    result = parse(source)
    assert result and result.search
    video = result.search.contents[0]
    assert video.title == "茶 & 饭"
    assert video.ext["duration"] == 3840
    assert video.counts.plays == 12000 and video.ext["counts_approx"] is True
    for kind in ("ssr__search", "x__web-interface__wbi__search__type"):
        last = parse(capture(kind, "last_page"))
        assert last and last.search and not last.search.has_more


def test_category_and_tags() -> None:
    path = ROOT / "ssr__search" / "20261102-tags.json"
    source = Capture.model_validate(json.loads(path.read_text())["capture"])
    first = source.body["result"][0]
    first.update(typename="数码", tag="手机, 评测,,手机")
    source.body["result"][1].update(typename="", tag="")
    result = parse(source)
    assert result and result.search
    videos = result.search.contents
    assert (videos[0].ext["tname"], videos[0].tags) == ("数码", ["手机", "评测"])
    assert "tname" not in videos[1].ext and videos[1].tags == []
    # 视频页 SSR 的 tname、tname_v2 实测都是空串：不写分区，免得盖掉搜索阶段的值。
    detail = parse(capture("ssr__video"))
    assert detail and detail.content
    assert detail.content.ext["tid_v2"] and "tname" not in detail.content.ext
    assert detail.content.tags == []
    source = capture("ssr__video")
    source.body["tname_v2"] = "数码"
    detail = parse(source)
    assert detail and detail.content and detail.content.ext["tname"] == "数码"


def test_comments_top_preview_and_pagination() -> None:
    source = capture("x__v2__reply__wbi__main")
    root = source.body["data"]["replies"][0]
    source.body["data"]["top_replies"] = [root]
    result = parse(source)
    assert result and result.comments
    comments = result.comments.comments
    assert len({comment.platform_id for comment in comments}) == len(comments)
    assert comments[0].platform_id == str(root["rpid"])
    assert comments[0].root_platform_id is None and comments[0].parent_platform_id is None
    child = root["replies"][0]
    actual = next(comment for comment in comments if comment.platform_id == str(child["rpid"]))
    assert actual.root_platform_id == str(child["root"])
    assert actual.parent_platform_id == str(child["parent"])
    assert actual.content_platform_id == str(child["oid"])
    for kind in ("x__v2__reply__wbi__main", "x__v2__reply__reply"):
        last = parse(capture(kind, "last_page"))
        assert last and last.comments and not last.comments.has_more


@pytest.mark.parametrize(
    "kind",
    [
        "ssr__search",
        "x__web-interface__wbi__search__type",
        "x__v2__reply__wbi__main",
        "x__v2__reply__reply",
    ],
)
def test_empty_is_not_page_change(kind: str) -> None:
    result = parse(capture(kind, "empty"))
    assert result and result.report.items == 0 and not result.report.nonempty_response


def test_missing_core_and_secondary_fields() -> None:
    source = capture("ssr__search")
    source.body["result"] = [dict(source.body["result"][0], bvid="")]
    result = parse(source)
    assert result and result.report.nonempty_response
    assert result.report.items == 0 and result.report.skipped_missing_core == 1
    source = capture("ssr__video")
    source.body["stat"]["like"] = "--"
    result = parse(source)
    assert result and result.content and result.content.counts.likes is None
    assert result.report.missing_fields["likes"] == 1
    source = capture("x__v2__reply__wbi__main")
    source.body["data"]["replies"] = [{"rpid": 3, "oid": 4, "content": {}}]
    source.body["data"]["top_replies"] = []
    result = parse(source)
    assert result and result.report.items == 0 and result.report.skipped_missing_core == 1


def test_ignored_responses_and_duplicate_top_preview() -> None:
    assert parse(capture("x__player__wbi__v2", "with_subtitle")) is None
    assert parse(capture("x__v2__reply__wbi__main", "risk")) is None
    source = capture("x__v2__reply__wbi__main")
    root = source.body["data"]["replies"][0]
    source.body["data"]["top_replies"] = [dict(root, replies=None)]
    result = parse(source)
    assert result and result.comments
    assert str(root["replies"][0]["rpid"]) in {
        comment.platform_id for comment in result.comments.comments
    }


def test_subtitles_and_registry() -> None:
    source = capture("subtitle")
    result = parse(source)
    assert result and len(result.subtitles) == 1
    subtitle = result.subtitles[0]
    assert subtitle.content_platform_id == source.body["bvid"]
    assert (
        subtitle.part_id == str(source.body["cid"]) and subtitle.part_title == source.body["part"]
    )
    assert subtitle.ai_generated and subtitle.segments
    failed = parse(capture("subtitle", "not_found"))
    assert failed and not failed.subtitles and failed.report.missing_fields["subtitles"] == 1
    assert parser_for("bili") is parse
