from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent, DeferredToolRequests

from gleanery.agent.prompts import SYSTEM_PROMPT

if TYPE_CHECKING:
    from gleanery.agent.deps import AgentDeps


def build_agent() -> Agent[AgentDeps, str | DeferredToolRequests]:
    from gleanery.agent import tools
    from gleanery.agent.deps import AgentDeps
    from gleanery.agent.tools import data, datasets, export, reports

    # 计划参数是嵌套结构，真模型（2026-11-02 冒烟，MiniMax）一次重试内常改不对，放宽到 3 次。
    agent = Agent(
        deps_type=AgentDeps,
        output_type=[str, DeferredToolRequests],
        instructions=SYSTEM_PROMPT,
        retries=3,
    )
    agent.tool(tools.propose_collection_plan)
    agent.tool(tools.get_collection_plan)
    agent.tool(tools.update_collection_plan)
    agent.tool(tools.start_collection)
    agent.tool(tools.get_collection_status)
    agent.tool(tools.stop_collection)
    agent.tool(tools.get_platform_status)
    agent.tool(tools.list_datasets)
    agent.tool(data.query_contents)
    agent.tool(data.get_content)
    agent.tool(data.query_comments)
    agent.tool(data.aggregate)
    agent.tool(data.count_mentions)
    agent.tool(data.run_sql)
    agent.tool(datasets.save_as_dataset)
    agent.tool(datasets.update_dataset)
    agent.tool(datasets.remove_from_dataset)
    agent.tool(datasets.delete_dataset)
    agent.tool(export.export_dataset)
    agent.tool(reports.save_report)
    agent.tool(reports.update_report)
    agent.tool(reports.get_report)
    agent.tool(reports.list_reports)
    return agent
