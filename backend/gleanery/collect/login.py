"""扫码登录与预热的后台编排。"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gleanery.api.errors import ApiError
from gleanery.api.schemas_collect import LoginPhase, LoginStatus
from gleanery.collect.runtime import PlatformRuntime
from gleanery.collect.service import CollectService
from gleanery.collect.settings import warmup_enabled
from gleanery.collect.types import WARMUP_MINUTES_DEFAULT
from gleanery.events import EventBus
from gleanery.platforms.errors import BrowserDisconnected, ProfileInUse
from gleanery.platforms.types import Platform

logger = logging.getLogger(__name__)


class LoginCoordinator:
    def __init__(
        self,
        runtime: PlatformRuntime | None,
        collect: CollectService,
        sessionmaker: async_sessionmaker[AsyncSession],
        events: EventBus,
    ) -> None:
        self.runtime = runtime
        self.collect = collect
        self.sessionmaker = sessionmaker
        self.events = events
        self.statuses: dict[Platform, LoginStatus] = {}
        self.tasks: dict[Platform, asyncio.Task[None]] = {}

    def status(self, platform: Platform) -> LoginStatus:
        status = self.statuses.get(platform, LoginStatus(phase="idle"))
        browser = (
            self.runtime.browser_kind(platform)
            if self.runtime and platform in self.runtime.platforms
            else None
        )
        return status.model_copy(update={"browser": browser})

    def start(self, platform: Platform) -> None:
        if platform in self.tasks and not self.tasks[platform].done():
            raise ApiError(409, "LOGIN_IN_PROGRESS", "该平台正在登录")
        if self.runtime is None or platform not in self.runtime.platforms:
            raise ApiError(409, "PLATFORM_UNSUPPORTED", "该平台暂无运行时")
        self._update(platform, "waiting_scan")
        self.tasks[platform] = asyncio.create_task(self._run(platform, self.runtime))

    def _update(self, platform: Platform, phase: LoginPhase, message: str | None = None) -> None:
        self.statuses[platform] = LoginStatus(phase=phase, message=message)
        self.events.publish("login.updated", {"platform": platform, "phase": phase})

    async def _run(self, platform: Platform, runtime: PlatformRuntime) -> None:
        try:
            success = await runtime.login(platform, lambda phase: self._update(platform, phase))
            if not success:
                if self.status(platform).phase != "timeout":
                    self._update(platform, "timeout")
                return
            async with self.sessionmaker() as session:
                enabled = await warmup_enabled(session)
            minutes = WARMUP_MINUTES_DEFAULT if enabled else None
            await self.collect.on_login_succeeded(platform, minutes)
            if self.status(platform).phase != "succeeded":
                self._update(platform, "succeeded")
        except ProfileInUse:
            self._update(platform, "failed", "配置目录被另一个程序占用")
        except BrowserDisconnected as error:
            self._update(platform, "failed", str(error))
        except Exception:
            logger.exception("扫码登录失败：%s", platform)
            self._update(platform, "failed", "登录失败，请重试")
        else:
            if minutes is not None:
                await self._warmup(platform, runtime, minutes)

    async def _warmup(self, platform: Platform, runtime: PlatformRuntime, minutes: float) -> None:
        # 预热失败不影响已成功的登录，只记日志；预热截止时间到了排队任务照常开始。
        try:
            await runtime.warmup(platform, minutes)
        except BrowserDisconnected as error:
            logger.warning("登录后预热中止：%s，%s", platform, error)
        except Exception:
            logger.exception("登录后预热失败：%s", platform)

    async def close(self) -> None:
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
