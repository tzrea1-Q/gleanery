import json
from pathlib import Path

import pytest

from gleanery.platforms.errors import PageChanged
from gleanery.platforms.types import Capture, ContentRef, Depth
from gleanery.platforms.xhs.fetcher import assemble

ROOT = Path(__file__).parents[2] / "fixtures" / "xhs"
NOTE = "69f0dae10000000023005a98"
FIRST_ROOT = "69f0dc7e000000002701f54a"


def capture(kind: str, case: str = "normal") -> Capture:
    return Capture.model_validate(
        json.loads((ROOT / kind / f"20261103-{case}.json").read_text())["capture"]
    )


def ref(**ext: str) -> ContentRef:
    return ContentRef(
        platform="xhs",
        platform_id=NOTE,
        url=f"https://www.xiaohongshu.com/explore/{NOTE}",
        ext=ext,
    )


def opened() -> list[Capture]:
    """同一次录制里打开笔记：详情、第 1 页一级评论、点开第一条一级评论的"展开"。"""
    page = capture("comment__page")
    return [
        capture("feed"),
        page,
        capture("comment__sub__page"),
        # 驱动在评论截获和展开之间可能再收到同一页，重复的评论只留一条。
        page,
    ]


def test_assemble_comments_and_truncation() -> None:
    depth = Depth(comments=3, sub_comments=True, sub_comments_per_root=4)
    result = assemble(ref(), depth, opened())
    assert result.content.platform_id == NOTE and result.content.completeness == "detail"
    roots = [item for item in result.comments if item.root_platform_id is None]
    assert len(roots) == 3
    assert len({item.platform_id for item in result.comments}) == len(result.comments)
    first = [item for item in result.comments if item.root_platform_id == FIRST_ROOT]
    # 内嵌的 1 条加展开得到的 5 条，截到每条一级评论 4 条。
    assert len(first) == 4
    assert {item.root_platform_id for item in result.comments if item.root_platform_id} <= {
        item.platform_id for item in roots
    }
    assert all(item.content_platform_id == NOTE for item in result.comments)
    assert result.subtitles == []


def test_assemble_without_sub_comments() -> None:
    result = assemble(ref(), Depth(comments=100), opened())
    assert result.comments and all(item.root_platform_id is None for item in result.comments)
    assert len(result.comments) == 5


def test_assemble_keeps_ref_token() -> None:
    result = assemble(ref(xsec_token="tok", xsec_source="pc_share"), Depth(), [capture("feed")])
    assert result.content.ext["xsec_token"] == "tok"
    assert result.content.ext["xsec_source"] == "pc_share"
    assert "xsec_token" not in assemble(ref(), Depth(), [capture("feed")]).content.ext


def test_assemble_from_ssr_note() -> None:
    result = assemble(ref(), Depth(), [capture("ssr__note")])
    assert result.content.completeness == "detail" and result.comments == []


def test_assemble_ignores_search_pages_loaded_along_the_way() -> None:
    """打开笔记途中页面翻出的搜索页已存为原始截获，不算进这条内容的解析统计。"""
    alone = assemble(ref(), Depth(), [capture("feed")]).report
    assert assemble(ref(), Depth(), [capture("search__notes"), capture("feed")]).report == alone


def test_assemble_without_detail() -> None:
    with pytest.raises(PageChanged):
        assemble(ref(), Depth(comments=10), [capture("comment__page"), capture("feed", "empty")])
