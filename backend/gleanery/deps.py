"""可注入的依赖。

生产装配与测试装配（`tests/e2e/` 的 app 工厂）都构造一个 `AppDeps` 交给 `create_app`，
生产代码里没有测试开关。
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import tzinfo
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

import httpx2
from pydantic_ai.models import Model
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from gleanery.collect.runtime import PlatformRuntime
    from gleanery.llm.chatgpt import ChatGPTPlan


class Clock(Protocol):
    """时钟。采集限速、冷却等都经它计时，测试注入假时钟。"""

    def now_ms(self) -> int:
        """当前 UTC 毫秒时间戳。"""
        ...

    async def sleep(self, seconds: float) -> None: ...


@dataclass(frozen=True)
class ResolvedModel:
    """一轮 Agent 运行所用的模型。"""

    model: Model
    model_name: str
    config_id: int | None = None
    kind: str = "openai_compatible"
    """模型配置的类型，决定上游错误怎么分类。"""


class ModelResolver(Protocol):
    """解析当前模型；没有可用的当前模型时返回 None。"""

    def __call__(self, session: AsyncSession) -> Awaitable[ResolvedModel | None]: ...


CredentialBackend = Literal["keyring", "file", "memory"]


class CredentialStore(Protocol):
    """模型配置的凭证存放。键是模型配置 ID，值是 API Key 等秘密，绝不写日志。"""

    backend: CredentialBackend

    def get(self, config_id: int) -> str | None: ...
    def set(self, config_id: int, secret: str) -> None: ...
    def delete(self, config_id: int) -> None: ...


@dataclass(frozen=True)
class AppDeps:
    data_dir: Path
    """应用数据目录，数据库、锁文件、凭证兜底文件都在这里。"""
    launch_token: str
    """本次启动的随机令牌，经 `/auth/launch` 换成 HttpOnly Cookie。"""
    port: int
    """本进程监听的 127.0.0.1 端口，用于推出允许的 Host 与 Origin。"""
    clock: Clock
    model_resolver: ModelResolver
    credential_store: CredentialStore
    static_dir: Path | None = None
    """前端构建产物目录；为 None 时不托管前端。"""
    extra_origins: frozenset[str] = field(default_factory=frozenset)
    """额外放行的 Origin（含 scheme 与端口），如开发时的 Vite。对应的 Host 一并放行。"""
    llm_transport: httpx2.AsyncBaseTransport | None = None
    """LLM 提供商 HTTP 请求所用的 transport；测试注入假服务器。"""
    chatgpt: ChatGPTPlan | None = None
    """ChatGPT 套餐的登录与凭证；resolver 必须用同一个实例。为 None 时相关路由返回 503。"""
    platform_runtime: PlatformRuntime | None = None
    """平台运行时（浏览器、取数、扫码）；为 None 时不执行采集任务，测试注入假的。"""
    tz: tzinfo | None = None
    """界面以外的本地时区（查询工具的时间、导出、每日额度）；None 为本机时区，测试注入固定时区。"""
