import pytest

from gleanery.collect.plan import PlanBody, PlatformSection


@pytest.mark.parametrize(
    "keywords",
    [["充电剩余时长"], "充电剩余时长", {"item": "充电剩余时长"}, {"item": ["充电剩余时长"]}],
)
def test_keywords_accept_model_quirks(keywords: object) -> None:
    # 真模型把字符串数组写成单个字符串或 {"item": …} 时，也按列表收下。
    section = PlatformSection.model_validate(
        {"platform": "bili", "keywords": keywords, "depth": {}, "quantity": 5}
    )
    assert section.keywords == ["充电剩余时长"]


def test_multi_key_object_still_rejected() -> None:
    with pytest.raises(ValueError):
        PlatformSection.model_validate(
            {"platform": "bili", "keywords": {"a": "x", "b": "y"}, "depth": {}, "quantity": 5}
        )


def test_tool_schema_has_field_descriptions() -> None:
    schema = PlanBody.model_json_schema()
    section = schema["$defs"]["PlatformSection"]["properties"]
    assert "JSON 字符串数组" in section["keywords"]["description"]
    assert "楼中楼" in schema["$defs"]["Depth"]["properties"]["sub_comments"]["description"]


@pytest.mark.parametrize("wrap", ["item", "list"])
def test_sections_accept_item_wrapper(wrap: str) -> None:
    section = {"platform": "bili", "keywords": ["x"], "depth": {}, "quantity": "5"}
    sections = {"item": section} if wrap == "item" else {"item": [section]}
    body = PlanBody.model_validate({"title": "t", "sections": sections})
    assert len(body.sections) == 1 and body.sections[0].quantity == 5


def test_missing_depth_fields_take_platform_defaults() -> None:
    section = PlatformSection.model_validate(
        {"platform": "bili", "keywords": ["x"], "depth": {"comments": 20}, "quantity": 5}
    )
    assert section.depth.comments == 20
    assert section.depth.subtitles is True and section.depth.detail is True


def test_sub_comments_without_count_take_ten() -> None:
    section = PlatformSection.model_validate(
        {"platform": "bili", "keywords": ["x"], "depth": {"sub_comments": True}, "quantity": 5}
    )
    assert section.depth.sub_comments_per_root == 10


@pytest.mark.parametrize("depth", [{"subtitles": True}, {"subtitles": False}])
def test_xhs_subtitles_are_disabled(depth: dict[str, bool]) -> None:
    section = PlatformSection.model_validate({"platform": "xhs", "depth": depth, "quantity": 0})
    assert section.depth.subtitles is False
