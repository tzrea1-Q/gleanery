import json
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, DeltaToolCalls, FunctionModel
from sqlalchemy.ext.asyncio import AsyncSession

from gleanery.app import create_app
from gleanery.clock import SystemClock
from gleanery.deps import AppDeps, ResolvedModel
from gleanery.store.models import ModelConfig
from gleanery.store.repo_settings import get_setting
from tests.e2e.fixture_runtime import FixtureRuntime
from tests.support.memory import MemoryCredentialStore

PLAN_REPLY = "已起草计划，请在卡片上检查后确认。"
START_REPLY = "采集已开始，进度会显示在卡片和工作区。"


def _plan(text: str) -> dict:
    keyword = "风控测试" if "风控" in text else "咖啡"
    sections = [
        {
            "platform": "bili",
            "keywords": [keyword],
            "quantity": 3,
            "depth": {"detail": True, "comments": 20, "sub_comments": False, "subtitles": True},
        }
    ]
    if text.startswith("两个平台"):
        sections.append(
            {
                "platform": "xhs",
                "keywords": ["露营装备"],
                "quantity": 3,
                "depth": {"detail": True, "comments": 20, "sub_comments": True},
            }
        )
    return {
        "title": f"{'B 站和小红书' if len(sections) > 1 else 'B 站'}{keyword}",
        "follow_up": "整理成报告" if "整理" in text else None,
        "new_dataset_name": f"{keyword}数据集",
        "sections": sections,
    }


def _latest_plan_id(messages: list[ModelMessage]) -> int | None:
    for message in reversed(messages):
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if (
                    isinstance(part, ToolReturnPart)
                    and part.tool_name == "propose_collection_plan"
                    and isinstance(part.content, dict)
                ):
                    return part.content.get("plan_id")
    return None


async def stream(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | DeltaToolCalls]:
    """e2e 的脚本模型：说"采集…""两个平台…"就起草计划，说"开始"就启动采集，说"进度"就回显系统注入，其余原样回显。"""
    last = messages[-1]
    if isinstance(last, ModelRequest):
        returns = [part for part in last.parts if isinstance(part, ToolReturnPart)]
        if returns:
            result = returns[-1]
            if result.tool_name == "list_datasets" and isinstance(result.content, dict):
                dataset_id = result.content["datasets"][0]["id"]
                yield {0: DeltaToolCall("query_contents", json.dumps({"dataset_id": dataset_id}))}
            elif result.tool_name == "query_contents" and isinstance(result.content, dict):
                dataset_id = result.content["dataset_id"]
                content_id = result.content["items"][0]["content_id"]
                yield {
                    0: DeltaToolCall(
                        "save_report",
                        json.dumps(
                            {
                                "title": "咖啡报告",
                                "dataset_id": dataset_id,
                                "markdown": f"| 主题 | 结论 |\n| --- | --- |\n| 咖啡 | 讨论 |\n\n参考 [[c:{content_id}]]",
                            },
                            ensure_ascii=False,
                        ),
                    )
                }
            elif result.tool_name == "save_report":
                yield "报告已写好。"
            else:
                yield PLAN_REPLY if result.tool_name == "propose_collection_plan" else START_REPLY
            return
    for message in reversed(messages):
        if isinstance(message, ModelRequest):
            for part in reversed(message.parts):
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    text = part.content
                    if text.startswith("系统事件"):
                        yield "已按后续意图整理完毕"
                    elif text.startswith(("额度用尽", "额度立刻用尽")):
                        if text.startswith("额度用尽"):
                            yield "已写出的一半"
                        raise ModelHTTPError(
                            429,
                            "e2e-model",
                            {"code": "subscription_sharing_usage_limit_exceeded"},
                        )
                    elif text.startswith("写报告"):
                        yield {0: DeltaToolCall("list_datasets", "{}")}
                    elif text.startswith("开始") and (plan_id := _latest_plan_id(messages)):
                        yield {
                            0: DeltaToolCall("start_collection", json.dumps({"plan_id": plan_id}))
                        }
                    elif text.startswith("进度"):
                        # 回显本轮的系统注入，用来检查注入是否到达模型。
                        instructions = info.instructions or ""
                        start = instructions.find("系统注入（")
                        yield instructions[start:] if start >= 0 else "没有新的任务变化"
                    elif text.startswith(("采集", "两个平台")):
                        yield {
                            0: DeltaToolCall(
                                "propose_collection_plan",
                                json.dumps({"plan": _plan(text)}, ensure_ascii=False),
                            )
                        }
                    else:
                        yield "收到："
                        yield text
                    return


async def backup_stream(
    messages: list[ModelMessage], info: AgentInfo
) -> AsyncIterator[str | DeltaToolCalls]:
    last = messages[-1]
    if isinstance(last, ModelRequest) and any(
        isinstance(part, UserPromptPart) and part.content == "凭证失效" for part in last.parts
    ):
        raise ModelHTTPError(401, "e2e-backup", {"code": "invalid_api_key"})
    yield "备用模型的回复"


def build_e2e_deps(
    data_dir: Path, port: int = 8799, token: str = "e2e-token", static_dir: Path | None = None
) -> AppDeps:
    model = FunctionModel(stream_function=stream)
    backup = FunctionModel(stream_function=backup_stream)

    async def resolve(session: AsyncSession) -> ResolvedModel | None:
        current = await get_setting(session, "current_model")
        config = await session.get(ModelConfig, current["config_id"]) if current else None
        if not config or config.status != "ok":
            return None
        if not any(
            f["name"] == current["model"] and f["tool_test"] == "ok" for f in config.favorites
        ):
            return None
        scripted = backup if current["model"] == "e2e-backup" else model
        return ResolvedModel(scripted, current["model"], config.id)

    return AppDeps(
        data_dir=data_dir,
        launch_token=token,
        port=port,
        clock=SystemClock(),
        model_resolver=resolve,
        credential_store=MemoryCredentialStore(),
        static_dir=static_dir or Path(__file__).resolve().parents[3] / "frontend/dist",
        platform_runtime=FixtureRuntime(),
    )


def create_e2e_app(deps: AppDeps) -> FastAPI:
    return create_app(deps)
