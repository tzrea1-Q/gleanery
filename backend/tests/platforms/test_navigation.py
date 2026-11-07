import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

from gleanery.platforms.errors import TransientError
from gleanery.platforms.navigation import goto

URL = "https://www.xiaohongshu.com/explore/abc?xsec_token=secret"


class Page:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.visited: list[str] = []

    async def goto(self, url: str, *, wait_until: str) -> None:
        assert wait_until == "domcontentloaded"
        self.visited.append(url)
        if self.error is not None:
            raise self.error


async def test_goto_passes_through_on_success() -> None:
    page = Page()
    await goto(page, URL)
    assert page.visited == [URL]


@pytest.mark.parametrize(
    "error",
    [
        PlaywrightTimeout(f'Page.goto: Timeout 30000ms exceeded.\n  - navigating to "{URL}"'),
        PlaywrightError(f"Page.goto: net::ERR_CONNECTION_RESET at {URL}"),
    ],
)
async def test_goto_turns_network_errors_into_transient(error: Exception) -> None:
    with pytest.raises(TransientError) as caught:
        await goto(Page(error), URL)
    # 原异常带 URL（含 xsec_token），不能随回溯进日志。
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    assert "secret" not in str(caught.value)


async def test_goto_keeps_other_errors() -> None:
    closed = PlaywrightError("Page.goto: Target page, context or browser has been closed")
    with pytest.raises(PlaywrightError):
        await goto(Page(closed), URL)
