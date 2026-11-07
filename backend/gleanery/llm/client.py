from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import httpx2
from openai import AsyncOpenAI
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.providers.openai import OpenAIProvider

from gleanery.store.models import ModelConfig

if TYPE_CHECKING:
    from gleanery.llm.chatgpt import ChatGPTPlan

# 流式回复两块之间可能隔很久（推理模型先思考），读超时不能用默认的 5 秒。
LLM_TIMEOUT = httpx2.Timeout(600, connect=15)


def make_http_client(transport: httpx2.AsyncBaseTransport | None) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=transport, timeout=LLM_TIMEOUT)


def make_model(
    config: ModelConfig,
    model: str,
    secret: str | None,
    http_client: httpx2.AsyncClient,
    chatgpt: ChatGPTPlan | None = None,
) -> Model:
    if config.kind == "anthropic":
        from gleanery.llm.anthropic import make_anthropic_model

        return make_anthropic_model(config, model, secret, http_client)
    if config.kind == "chatgpt_plan":
        if chatgpt is None:
            raise RuntimeError("没有装配 ChatGPT 套餐")
        return chatgpt.make_model(config, model)
    client = AsyncOpenAI(
        api_key=secret or "unused",
        base_url=config.base_url,
        http_client=cast(Any, http_client),
        max_retries=0,
    )
    if config.preset == "deepseek":
        provider = DeepSeekProvider(openai_client=client)
    else:
        provider = OpenAIProvider(openai_client=client)
    if config.api_style == "responses":
        return OpenAIResponsesModel(model, provider=provider)
    return OpenAIChatModel(model, provider=provider)
