from typing import Any

import pytest

from gleanery.platforms.bili import selectors
from gleanery.platforms.bili.login import login, warmup
from gleanery.platforms.errors import RiskDetected
from tests.platforms.bili.test_driver_fake_page import FakePage, Response


class Clock:
    def __init__(self) -> None:
        self.time = 0

    def now_ms(self) -> int:
        return self.time

    async def sleep(self, seconds: float) -> None:
        self.time += int(seconds * 1000)


class LoginPage(FakePage):
    def __init__(self, has_cookie: bool) -> None:
        super().__init__()
        self.context = self
        self.has_cookie = has_cookie

    async def cookies(self) -> list[dict[str, str]]:
        return [{"name": "SESSDATA"}] if self.has_cookie else []

    async def goto(self, url: str, *, wait_until: str) -> None:
        if self.callback:
            await super().goto(url, wait_until=wait_until)

    async def click(self) -> None:
        pass


async def test_login() -> None:
    phases: list[Any] = []
    assert await login(LoginPage(True), Clock(), phases.append)
    assert phases == ["waiting_scan", "verifying", "succeeded"]


async def test_timeout_and_warmup() -> None:
    clock = Clock()
    phases: list[Any] = []
    assert not await login(LoginPage(False), clock, phases.append)
    assert clock.time == 600_000 and phases == ["waiting_scan", "timeout"]
    await warmup(LoginPage(False), 0.1, clock)
    assert clock.time == 606_000


async def test_cookie_without_server_login_is_rejected() -> None:
    class GuestPage(LoginPage):
        async def goto(self, url: str, *, wait_until: str) -> None:
            if self.callback:
                self.callback(Response(selectors.NAV, {"data": {"isLogin": False}}))

    phases: list[Any] = []
    with pytest.raises(RiskDetected, match="nav_not_login"):
        await login(GuestPage(True), Clock(), phases.append)
    assert phases == ["waiting_scan", "verifying"]
