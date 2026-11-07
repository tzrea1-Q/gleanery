import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.deps import CredentialStore, ModelResolver, ResolvedModel
from gleanery.llm.chatgpt import ChatGPTPlan
from gleanery.llm.client import make_http_client, make_model
from gleanery.llm.presets import PRESETS
from gleanery.store.models import ModelConfig
from gleanery.store.repo_settings import get_setting


def make_model_resolver(
    credential_store: CredentialStore,
    llm_transport: httpx2.AsyncBaseTransport | None = None,
    chatgpt: ChatGPTPlan | None = None,
) -> ModelResolver:
    # 所有对话轮次共用一个连接池，进程退出时随之释放。
    http_client = make_http_client(llm_transport)

    async def resolve_current_model(session: AsyncSession) -> ResolvedModel | None:
        current = await get_setting(session, "current_model")
        if not current:
            return None
        config = await session.get(ModelConfig, current["config_id"])
        if (
            not config
            or config.status != "ok"
            or not any(
                f["name"] == current["model"] and f["tool_test"] == "ok" for f in config.favorites
            )
        ):
            return None
        secret = credential_store.get(config.id)
        if not secret and any(p.id == config.preset and p.key_required for p in PRESETS):
            return None
        return ResolvedModel(
            make_model(config, current["model"], secret, http_client, chatgpt),
            current["model"],
            config.id,
            config.kind,
        )

    return resolve_current_model
