"""Anthropic 提供商。"""

import httpx2
from anthropic import AsyncAnthropic
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from gleanery.store.models import ModelConfig


def make_anthropic_model(
    config: ModelConfig, model: str, secret: str | None, http_client: httpx2.AsyncClient
) -> Model:
    client = AsyncAnthropic(
        api_key=secret or "unused", base_url=config.base_url, http_client=http_client, max_retries=0
    )
    return AnthropicModel(model, provider=AnthropicProvider(anthropic_client=client))


async def refresh_anthropic(
    config: ModelConfig, secret: str | None, transport: httpx2.AsyncBaseTransport | None, now: int
) -> None:
    """测连通、拉模型列表，结果写进 `config`，语义同 `probe.refresh`。"""
    config.available_models = None
    config.model_labels = None
    config.models_fetched_at = now
    try:
        async with httpx2.AsyncClient(transport=transport, timeout=15) as client:
            params: dict[str, str | int] = {"limit": 1000}
            models: list[str] = []
            labels: dict[str, str] = {}
            seen: set[str] = set()
            while True:
                response = await client.get(
                    config.base_url.rstrip("/") + "/v1/models",
                    params=params,
                    headers={"x-api-key": secret or "", "anthropic-version": "2023-06-01"},
                )
                if response.status_code in (401, 403):
                    config.status, config.status_reason = "unavailable", "凭证无效"
                    return
                if response.status_code == 404:
                    config.status, config.status_reason = "ok", None
                    return
                if response.is_error:
                    config.status, config.status_reason = (
                        "unavailable",
                        f"上游 {response.status_code}",
                    )
                    return
                config.status, config.status_reason = "ok", None
                try:
                    page = response.json()
                    data = page["data"]
                    if not isinstance(data, list) or not all(
                        isinstance(item, dict) and isinstance(item.get("id"), str) for item in data
                    ):
                        return
                    for item in data:
                        models.append(item["id"])
                        if isinstance(item.get("display_name"), str):
                            labels[item["id"]] = item["display_name"]
                    if not page.get("has_more"):
                        config.available_models = models
                        config.model_labels = labels or None
                        return
                    cursor = page.get("last_id")
                    if not isinstance(cursor, str) or not cursor or cursor in seen:
                        return
                    seen.add(cursor)
                    params["after_id"] = cursor
                except (ValueError, KeyError, TypeError, AttributeError):
                    return
    except (httpx2.HTTPError, ValueError):
        config.status, config.status_reason = "unavailable", "连接失败"
