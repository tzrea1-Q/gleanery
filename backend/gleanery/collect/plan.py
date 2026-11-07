"""采集计划的字段（ADR-0002）。草稿存在 `collection_plan.body`。"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from gleanery.platforms.types import Depth, Platform, SortOrder, TimeRange


def _lenient_list(value: Any) -> Any:
    # 2026-11-02 冒烟：MiniMax 把数组写成 {"item": …}（字符串数组和 sections 都出现过），
    # 看到校验错误后连续几次照旧。单键对象取出里面的值，单个值包成列表。
    # 一个平台分段至少有三个必填键，所以单键对象不会是分段本身。
    if isinstance(value, dict) and len(value) == 1:  # pyright: ignore[reportUnknownArgumentType]
        value = next(iter(value.values()))  # pyright: ignore[reportUnknownArgumentType]
    if isinstance(value, (str, int, dict)):
        return [value]
    return value


StringList = Annotated[list[str], BeforeValidator(_lenient_list)]
IdList = Annotated[list[int], BeforeValidator(_lenient_list)]
"""Agent 工具参数里的 ID 数组，同样宽松。"""


class PlatformSection(BaseModel):
    """一个平台的采集目标与深度。"""

    model_config = ConfigDict(use_attribute_docstrings=True)

    platform: Platform
    """bili 为 B 站，xhs 为小红书。"""
    keywords: StringList = Field(default_factory=list)
    """搜索关键词，JSON 字符串数组，如 ["咖啡", "手冲"]。"""
    targets: StringList = Field(default_factory=list)
    """指定内容：用户贴的链接，或 `content:<内部 ID>`。JSON 字符串数组。不计入 quantity。"""
    depth: Depth
    quantity: int = Field(ge=0)
    """关键词搜索部分的内容总条数，按顺序均分给各关键词，余额顺延。只有指定内容时填 0。"""
    sort: SortOrder = "default"
    """default 综合，hot 最热，new 最新。"""
    time_range: TimeRange | None = None
    """发布时间范围，不限时为 null。"""

    @model_validator(mode="before")
    @classmethod
    def _platform_depth_defaults(cls, data: Any) -> Any:
        # 深度里没写的项取平台默认值，而不是 Depth 的通用默认（字幕关、评论 0）。
        # 2026-11-02 冒烟：模型改计划时漏写 subtitles，B 站字幕被悄悄关掉。
        if isinstance(data, dict) and isinstance(data.get("depth"), dict):  # pyright: ignore[reportUnknownMemberType]
            platform = data.get("platform")  # pyright: ignore[reportUnknownMemberType]
            if platform in DEFAULT_DEPTH:
                defaults = DEFAULT_DEPTH[platform].model_dump()
                if data["depth"].get("sub_comments"):  # pyright: ignore[reportUnknownMemberType]
                    defaults["sub_comments_per_root"] = SUB_COMMENTS_PER_ROOT_DEFAULT
                data = {**data, "depth": {**defaults, **data["depth"]}}  # pyright: ignore[reportUnknownArgumentType]
        return data

    @model_validator(mode="after")
    def _xhs_no_subtitles(self) -> PlatformSection:
        if self.platform == "xhs" and self.depth.subtitles:
            self.depth = self.depth.model_copy(update={"subtitles": False})
        return self


class PlanBody(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)

    title: str
    """计划标题，一句话说明采什么。"""
    target_dataset_id: int | None = None
    """为 None 表示新建数据集。"""
    new_dataset_name: str | None = None
    """新建数据集时的名称。"""
    new_dataset_description: str | None = None
    """新建数据集时的说明。"""
    follow_up: str | None = None
    """后续意图：采集结束后 Agent 要接着做的整理要求。"""
    sections: Annotated[list[PlatformSection], BeforeValidator(_lenient_list)] = Field(min_length=1)
    """各平台分段，每个平台最多一段。"""


SUB_COMMENTS_PER_ROOT_DEFAULT = 10
"""要二级评论但没说数量时每条一级评论取几条，和系统提示里写的一致。"""

DEFAULT_DEPTH: dict[Platform, Depth] = {
    "bili": Depth(detail=True, comments=100, sub_comments=False, subtitles=True),
    "xhs": Depth(detail=True, comments=50, sub_comments=False),
}
