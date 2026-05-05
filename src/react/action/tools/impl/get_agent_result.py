from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from react.action.base import BaseAction


class GetAgentResultArgs(BaseModel):
    agent_id: str = Field(..., min_length=1, description="由 spawn_agent 返回的子智能体 ID")


class GetAgentResultAction(BaseAction):
    name: str = "get_agent_result"
    description: str = (
        "查询异步子智能体的执行状态和结果。"
        "参数：agent_id（由 spawn_agent 返回的 ID）。"
        "返回 status（running|done|failed|not_found）以及完成时的 answer。"
    )
    args_model: ClassVar[type[BaseModel]] = GetAgentResultArgs

    manager: Any = None  # CrewManager，构造时注入

    def execute(self, agent_id: str, **kwargs) -> str:
        if self.manager is None:
            return "Crew 管理器未初始化。"
        result = self.manager.get_result(agent_id)
        if result.status == "not_found":
            return f"未找到 agent_id={agent_id} 对应的子智能体任务。"
        if result.status == "running":
            return f"子智能体仍在运行中。\nagent_id: {agent_id}"
        if result.status == "failed":
            return f"子智能体执行失败。\nagent_id: {agent_id}\n错误: {result.error}"
        return f"子智能体已完成。\nagent_id: {agent_id}\n结果:\n{result.answer}"
