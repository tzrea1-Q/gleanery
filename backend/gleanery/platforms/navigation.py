from __future__ import annotations

from typing import Any, Protocol

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

from gleanery.platforms.errors import TransientError


class NavigationPage(Protocol):
    async def goto(self, url: str, *, wait_until: str) -> Any: ...


async def goto(page: NavigationPage, url: str) -> None:
    """导航超时和 net::ERR_ 连接错误转成 TransientError，由执行器按普通网络错误重试。

    其余错误原样抛出：页面被关、浏览器断开要由浏览器管理器判成断开。
    转换时丢掉原异常，因为 Playwright 的调用日志带完整 URL，小红书的 URL 里有 xsec_token。
    """
    try:
        await page.goto(url, wait_until="domcontentloaded")
    except PlaywrightTimeout:
        raise TransientError("navigation_timeout") from None
    except PlaywrightError as error:
        if "net::ERR_" not in str(error):
            raise
        raise TransientError("navigation_failed") from None
