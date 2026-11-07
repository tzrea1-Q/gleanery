import pytest

from gleanery.platforms.errors import PageChanged
from gleanery.platforms.scroll import AT_BOTTOM, SCROLL, scroll_until


class Page:
    def __init__(self, bottom_after: int | None = None) -> None:
        self.steps: list[int] = []
        self.bottom_after = bottom_after
        """滚到第几步才到底；None 表示拿不到位置。"""

    async def evaluate(self, expression: str, arg: object = None) -> object:
        if expression == AT_BOTTOM:
            return None if self.bottom_after is None else len(self.steps) >= self.bottom_after
        assert expression == SCROLL and isinstance(arg, int) and 500 <= arg <= 600
        self.steps.append(arg)
        return None


@pytest.mark.parametrize("success", [1, 3, None])
async def test_scroll(success: int | None) -> None:
    page = Page()

    async def received(seconds: float) -> bool:
        assert seconds == 1.5
        return len(page.steps) == success

    if success is None:
        with pytest.raises(PageChanged, match="missed_responses"):
            await scroll_until(page, received)
        assert len(page.steps) == 3
    else:
        await scroll_until(page, received)
        assert len(page.steps) == success


async def test_long_page_keeps_scrolling_until_bottom() -> None:
    # 一页评论很长：前 8 步都没到底，不算没等到；第 10 步才来下一页。
    page = Page(bottom_after=8)

    async def received(seconds: float) -> bool:
        return len(page.steps) == 10

    await scroll_until(page, received)
    assert len(page.steps) == 10


async def test_three_misses_at_bottom_is_page_changed() -> None:
    page = Page(bottom_after=5)

    async def received(seconds: float) -> bool:
        return False

    with pytest.raises(PageChanged, match="missed_responses"):
        await scroll_until(page, received)
    assert len(page.steps) == 7


async def test_endless_page_stops_at_max_steps() -> None:
    page = Page(bottom_after=10_000)

    async def received(seconds: float) -> bool:
        return False

    with pytest.raises(PageChanged):
        await scroll_until(page, received, max_steps=20)
    assert len(page.steps) == 20
