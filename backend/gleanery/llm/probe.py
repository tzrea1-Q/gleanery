import httpx2
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelRequest, PartStartEvent, ToolCallPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.tools import ToolDefinition

from gleanery.llm.anthropic import refresh_anthropic
from gleanery.llm.chatgpt import ChatGPTPlan
from gleanery.llm.client import make_http_client, make_model
from gleanery.store.models import ModelConfig


async def refresh(
    config: ModelConfig,
    secret: str | None,
    transport: httpx2.AsyncBaseTransport | None,
    now: int,
    chatgpt: ChatGPTPlan | None = None,
) -> None:
    if config.kind == "anthropic":
        await refresh_anthropic(config, secret, transport, now)
        return
    if config.kind == "chatgpt_plan":
        if chatgpt is None:
            raise RuntimeError("没有装配 ChatGPT 套餐")
        await chatgpt.refresh_models(config, now)
        return
    try:
        async with httpx2.AsyncClient(transport=transport, timeout=15) as client:
            response = await client.get(
                config.base_url.rstrip("/") + "/models",
                headers={"Authorization": f"Bearer {secret}"} if secret else {},
            )
        if response.status_code in (401, 403):
            config.status, config.status_reason = "unavailable", "凭证无效"
        elif response.status_code == 404:
            config.status, config.status_reason = "ok", None
        elif response.is_error:
            config.status, config.status_reason = "unavailable", f"上游 {response.status_code}"
        else:
            config.status, config.status_reason = "ok", None
        config.available_models = None
        if response.is_success:
            try:
                data = response.json()["data"]
                if isinstance(data, list) and all(
                    isinstance(item, dict) and isinstance(item.get("id"), str) for item in data
                ):
                    config.available_models = [item["id"] for item in data]
            except (ValueError, KeyError, TypeError):
                pass
        config.models_fetched_at = now
    except (httpx2.HTTPError, ValueError):
        config.status, config.status_reason = "unavailable", "连接失败"
        config.available_models = None
        config.models_fetched_at = now


async def probe_tool_call(
    config: ModelConfig,
    name: str,
    secret: str | None,
    transport: httpx2.AsyncBaseTransport | None,
    chatgpt: ChatGPTPlan | None = None,
) -> str | None:
    """带一个假工具发流式请求；模型调用了它就返回 None，否则返回失败原因。"""
    async with make_http_client(transport) as http_client:
        model = make_model(config, name, secret, http_client, chatgpt)
        params = ModelRequestParameters(
            function_tools=[ToolDefinition(name="probe", description="测试工具调用")]
        )
        try:
            async with model.request_stream(
                [ModelRequest(parts=[UserPromptPart(content="请调用 probe 工具。")])], None, params
            ) as stream:
                async for event in stream:
                    if (
                        isinstance(event, PartStartEvent)
                        and isinstance(event.part, ToolCallPart)
                        and event.part.tool_name == "probe"
                    ):
                        return None
            return "模型没有调用工具"
        except ModelHTTPError as exc:
            return f"上游 {exc.status_code}：{_brief(exc.body)}"
        except Exception as exc:
            return f"工具调用测试失败：{type(exc).__name__}: {_brief(str(exc))}"


def _brief(detail: object) -> str:
    """上游错误信息截短后给用户看。上游响应与 SDK 异常不含请求头，不会带出 Key。"""
    text = detail if isinstance(detail, str) else repr(detail)
    return text[:200]
