"""平台状态、扫码登录、探活与用户操作。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.api.deps import get_collect, get_login, get_session
from gleanery.api.errors import ApiError, ErrorBody
from gleanery.api.schemas_collect import PlatformOut
from gleanery.collect.login import LoginCoordinator
from gleanery.collect.service import CollectService
from gleanery.collect.types import DEFAULT_RATE_LIMITS
from gleanery.platforms.errors import (
    BrowserDisconnected,
    ProfileInUse,
    RiskDetected,
    TransientError,
)
from gleanery.platforms.types import Capture, CaptureSink, PaceKind, Pacer, Platform

router = APIRouter(prefix="/api/platforms", tags=["platforms"])
_errors: dict[int | str, dict[str, Any]] = {
    409: {"model": ErrorBody, "description": "PROFILE_IN_USE、LOGIN_IN_PROGRESS 等"},
    504: {"model": ErrorBody, "description": "NAVIGATION_FAILED：探活时打开平台页面超时"},
}
Session = Annotated[AsyncSession, Depends(get_session)]
Collect = Annotated[CollectService, Depends(get_collect)]
Login = Annotated[LoginCoordinator, Depends(get_login)]


class ProbeContext:
    def __init__(self) -> None:
        self.sink: CaptureSink = self
        self.pacer: Pacer = self

    async def save(self, capture: Capture) -> None:
        pass

    async def wait(self, kind: PaceKind) -> None:
        pass

    def log(self, message: str) -> None:
        pass


async def platform_output(
    platform: Platform, session: AsyncSession, collect: CollectService, login: LoginCoordinator
) -> PlatformOut:
    view = await collect.platform_view(session, platform)
    runtime = login.runtime
    running = (
        runtime.browser_running(platform) if runtime and platform in runtime.platforms else False
    )
    return PlatformOut(**view.model_dump(), login=login.status(platform), browser_running=running)


@router.get("", response_model=list[PlatformOut])
async def list_platforms(session: Session, collect: Collect, login: Login) -> list[PlatformOut]:
    """不为刷新而启动浏览器。"""
    return [
        await platform_output(platform, session, collect, login) for platform in DEFAULT_RATE_LIMITS
    ]


@router.post("/{platform}/login", response_model=PlatformOut, responses=_errors)
async def start_login(
    platform: Platform, session: Session, collect: Collect, login: Login
) -> PlatformOut:
    """打开专用 Chrome 的登录页，由用户扫码；立即返回，进度经 login.updated 事件推送。"""
    login.start(platform)
    return await platform_output(platform, session, collect, login)


@router.post("/{platform}/probe", response_model=PlatformOut, responses=_errors)
async def probe(
    platform: Platform, session: Session, collect: Collect, login: Login
) -> PlatformOut:
    runtime = login.runtime
    if runtime is None or platform not in runtime.platforms:
        raise ApiError(409, "PLATFORM_UNSUPPORTED", "该平台暂无运行时，无法探活")
    fetcher = runtime.fetcher(platform)
    try:
        result = await fetcher.probe(ProbeContext())
        await collect.on_probe(platform, result.logged_in, result.detail)
        if not result.logged_in:
            await collect.on_login_lost(platform)
    except RiskDetected as error:
        await collect.on_risk(platform, error.verdict, None)
    except ProfileInUse as error:
        raise ApiError(409, "PROFILE_IN_USE", "专用浏览器的配置目录被另一个程序占用") from error
    except BrowserDisconnected as error:
        raise ApiError(409, "BROWSER_DISCONNECTED", "浏览器连接已断开，请重试") from error
    except TransientError as error:
        raise ApiError(504, "NAVIGATION_FAILED", "打开平台页面超时或连不上，请稍后重试") from error
    finally:
        await fetcher.close()
    return await platform_output(platform, session, collect, login)


@router.post("/{platform}/unlock", response_model=PlatformOut, responses=_errors)
async def unlock(
    platform: Platform, session: Session, collect: Collect, login: Login
) -> PlatformOut:
    await collect.unlock(platform)
    return await platform_output(platform, session, collect, login)


@router.post("/{platform}/accept-page-change", response_model=PlatformOut, responses=_errors)
async def accept_page_change(
    platform: Platform, session: Session, collect: Collect, login: Login
) -> PlatformOut:
    """页面改版待确认 → 正常（"仍然继续"）。"""
    await collect.accept_page_change(platform)
    return await platform_output(platform, session, collect, login)
