"""ChatGPT 套餐的登录、凭证和 provider。"""

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from uuid import uuid4

import httpx2
from pydantic_ai.exceptions import UserError
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai_chatgpt import (
    CredentialsRefreshError,
    OpenAIChatGPTCredentials,
    OpenAIChatGPTOAuthFlow,
    OpenAIChatGPTProvider,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.deps import Clock, CredentialStore
from gleanery.llm.client import LLM_TIMEOUT
from gleanery.llm.errors import grant_rejected
from gleanery.store.models import ModelConfig
from gleanery.store.repo_settings import get_setting, set_setting

APP_NAME = "Gleanery"
PENDING_TTL_MS = 10 * 60 * 1000
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallbackResult:
    """回调结果只包含固定文案。"""

    status: int
    message: str
    changed: bool = False
    """配置有变化，要发事件让主页面刷新。"""


class CredentialSource:
    def __init__(self, store: CredentialStore, config_id: int) -> None:
        self.store = store
        self.config_id = config_id

    async def load(self) -> OpenAIChatGPTCredentials:
        data = json.loads(self.store.get(self.config_id) or "{}")
        return OpenAIChatGPTCredentials(**data)

    async def save(self, credentials: OpenAIChatGPTCredentials) -> None:
        self.store.set(self.config_id, json.dumps(asdict(credentials)))


class ChatGPTPlan:
    def __init__(
        self,
        credential_store: CredentialStore,
        clock: Clock,
        port: int,
        llm_transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.credential_store = credential_store
        self.clock = clock
        self.port = port
        self.llm_transport = llm_transport
        self.pending: dict[str, tuple[int, OpenAIChatGPTOAuthFlow]] = {}
        self.providers: dict[int, tuple[OpenAIChatGPTProvider, httpx2.AsyncClient]] = {}
        self.lock = asyncio.Lock()

    def _stored(self, config_id: int) -> dict:
        try:
            value = json.loads(self.credential_store.get(config_id) or "{}")
            return value if isinstance(value, dict) else {}
        except (ValueError, TypeError):
            return {}

    async def _config(self, session: AsyncSession) -> ModelConfig | None:
        return await session.scalar(select(ModelConfig).where(ModelConfig.kind == "chatgpt_plan"))

    def _provider(self, config: ModelConfig) -> tuple[OpenAIChatGPTProvider, httpx2.AsyncClient]:
        if config.id not in self.providers:
            client = httpx2.AsyncClient(transport=self.llm_transport, timeout=LLM_TIMEOUT)
            provider = OpenAIChatGPTProvider(
                credential_source=CredentialSource(self.credential_store, config.id),
                http_client=client,
            )
            provider.client.max_retries = 0
            self.providers[config.id] = (provider, client)
        return self.providers[config.id]

    async def _drop(self, config_id: int) -> None:
        cached = self.providers.pop(config_id, None)
        if cached:
            await cached[1].aclose()

    async def start(self, session: AsyncSession) -> str:
        config = await self._config(session)
        saved = self._stored(config.id) if config else {}
        host_id = await get_setting(session, "chatgpt_host_id")
        if not host_id:
            host_id = uuid4().urn
            await set_setting(session, "chatgpt_host_id", host_id)
            await session.commit()
        flow = OpenAIChatGPTOAuthFlow(
            app_name=APP_NAME,
            host_id=host_id,
            client_id=config.client_id if config else None,
            id_token_hint=saved.get("id_token"),
            redirect_uri=f"http://127.0.0.1:{self.port}/auth/callback",
        )
        now = self.clock.now_ms()
        self.pending = {
            key: item for key, item in self.pending.items() if now - item[0] <= PENDING_TTL_MS
        }
        self.pending[flow.state] = (now, flow)
        consent = bool(
            saved.get("scope") is not None
            and "chatgpt.tokens.use.direct" not in saved["scope"].split()
        )
        return flow.authorization_url(extra_params={"prompt": "consent"} if consent else None)

    async def complete(self, session: AsyncSession, params: dict[str, str]) -> CallbackResult:
        pending = self.pending.pop(params.get("state", ""), None)
        if not pending or self.clock.now_ms() - pending[0] > PENDING_TTL_MS:
            return CallbackResult(400, "登录已失效，请回到 Gleanery 重新连接。")
        if params.get("error"):
            return CallbackResult(200, "已取消连接，可以关闭此页面。")
        if not params.get("code"):
            return CallbackResult(400, "连接失败，请回到 Gleanery 重新连接。")
        try:
            credentials = await pending[1].exchange_code(
                params["code"], client_id=params.get("client_id")
            )
        except UserError as exc:
            if "different ChatGPT account" in str(exc):
                return CallbackResult(200, "要换账号，先在设置里删除这份配置。")
            return CallbackResult(200, "连接失败，请回到 Gleanery 重新连接。")
        except Exception as exc:
            # 令牌端点的错误消息只有地址和错误码；其他异常只记类型，免得带出别的内容。
            detail = exc if isinstance(exc, CredentialsRefreshError) else type(exc).__name__
            logger.warning("ChatGPT 登录换 token 失败：%s", detail)
            return CallbackResult(200, "连接失败，请回到 Gleanery 重新连接。")
        async with self.lock:
            config = await self._config(session)
            now = self.clock.now_ms()
            if config is None:
                config = ModelConfig(
                    kind="chatgpt_plan",
                    name="ChatGPT 套餐",
                    preset="chatgpt",
                    base_url="https://api.openai.com/v1",
                    api_style="responses",
                    status="needs_reconnect",
                    favorites=[],
                    created_at=now,
                    updated_at=now,
                )
                session.add(config)
                await session.flush()
            await self._drop(config.id)
            await CredentialSource(self.credential_store, config.id).save(credentials)
            config.client_id = credentials.client_id
            config.updated_at = now
            if not credentials.plan_usage_granted:
                config.status, config.status_reason = "needs_reconnect", "未授权使用 ChatGPT 套餐"
                config.available_models, config.model_labels = None, None
            else:
                await self.refresh_models(config, now)
            await session.commit()
            if config.status == "ok":
                return CallbackResult(200, "已连接，可以关闭此页面。", changed=True)
            return CallbackResult(
                200, f"已登录，但{config.status_reason}。回到 Gleanery 查看。", changed=True
            )

    def make_model(self, config: ModelConfig, model: str) -> Model:
        return OpenAIResponsesModel(model, provider=self._provider(config)[0])

    async def refresh_models(self, config: ModelConfig, now: int) -> None:
        if not self.has_refresh_token(config.id):
            return
        config.available_models, config.model_labels = None, None
        config.models_fetched_at = now
        try:
            response = await self._provider(config)[1].get("https://api.openai.com/v1/models")
            if response.status_code == 401:
                config.status, config.status_reason = "needs_reconnect", "授权已失效"
            elif (
                response.status_code == 403
                and "subscription_sharing_user_not_eligible" in response.text
            ):
                config.status, config.status_reason = "unavailable", "需要 Plus 或 Pro"
            elif response.is_error:
                config.status, config.status_reason = "unavailable", f"上游 {response.status_code}"
            else:
                config.status, config.status_reason = "ok", None
                try:
                    data = response.json()
                    items = data.get("data", data.get("models"))
                    if isinstance(items, list):
                        listed = [
                            item
                            for item in items
                            if isinstance(item, dict)
                            and item.get("visibility") == "list"
                            and isinstance(item.get("slug"), str)
                        ]
                        config.available_models = [item["slug"] for item in listed]
                        config.model_labels = {
                            item["slug"]: item["display_name"]
                            for item in listed
                            if isinstance(item.get("display_name"), str)
                        } or None
                except (ValueError, AttributeError):
                    pass
        except CredentialsRefreshError as exc:
            if grant_rejected(exc):
                config.status, config.status_reason = "needs_reconnect", "授权已失效"
            else:
                config.status, config.status_reason = "unavailable", "连接失败"
        except (httpx2.HTTPError, UserError):
            config.status, config.status_reason = "unavailable", "连接失败"

    async def _revoke(self, config: ModelConfig) -> None:
        token = self._stored(config.id).get("refresh_token")
        if not token:
            return
        try:
            async with httpx2.AsyncClient(
                transport=self.llm_transport, timeout=LLM_TIMEOUT
            ) as client:
                discovery = await client.get(
                    "https://auth.openai.com/.well-known/openid-configuration"
                )
                discovery.raise_for_status()
                endpoint = discovery.json()["revocation_endpoint"]
                if (
                    httpx2.URL(endpoint).scheme != "https"
                    or httpx2.URL(endpoint).host != "auth.openai.com"
                ):
                    raise ValueError("无效的撤销地址")
                response = await client.post(
                    endpoint,
                    data={
                        "token": token,
                        "token_type_hint": "refresh_token",
                        "client_id": config.client_id or "",
                    },
                )
                response.raise_for_status()
        except (httpx2.HTTPError, ValueError, KeyError, TypeError):
            logger.warning("撤销 ChatGPT 凭证失败，仍清理本地凭证")

    async def disconnect(self, config: ModelConfig) -> None:
        await self._revoke(config)
        saved = self._stored(config.id)
        self.credential_store.set(config.id, json.dumps({"id_token": saved.get("id_token")}))
        await self._drop(config.id)
        config.status, config.status_reason = "needs_reconnect", "已断开"

    async def forget(self, config: ModelConfig) -> None:
        await self._revoke(config)
        self.credential_store.delete(config.id)
        await self._drop(config.id)

    def has_refresh_token(self, config_id: int) -> bool:
        return bool(self._stored(config_id).get("refresh_token"))

    async def close(self) -> None:
        for config_id in list(self.providers):
            await self._drop(config_id)
