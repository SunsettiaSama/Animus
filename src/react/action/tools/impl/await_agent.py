from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from react.action.base import BaseAction


class AwaitAgentArgs(BaseModel):
    agent_id: str = Field(..., min_length=1, description="由 spawn_agent 返回的子智能体 ID")
    timeout: float = Field(300.0, ge=1.0, description="最长等待秒数，默认 300 秒")


class AwaitAgentAction(BaseAction):
    name: str = "await_agent"
    description: str = (
        "阻塞等待单个异步子智能体完成，返回其最终结果。"
        "参数：agent_id（由 spawn_agent 返回），timeout（最长等待秒数，默认 300）。"
        "返回 status 和 answer；超时则 status=timeout。"
    )
    args_model: ClassVar[type[BaseModel]] = AwaitAgentArgs

    manager: Any = None  # CrewManager，构造时注入

    def execute(self, agent_id: str, timeout: float = 300.0, **kwargs) -> str:
        if self.manager is None:
            return "Crew 管理器未初始化。"
        result = self.manager.await_agent(agent_id, timeout=timeout)
        if result.status == "not_found":
            return f"未找到 agent_id={agent_id} 对应的子智能体任务。"
        if result.status == "timeout":
            return f"等待超时（{timeout}s）。\nagent_id: {agent_id}"
        if result.status == "failed":
            return f"子智能体执行失败。\nagent_id: {agent_id}\n错误: {result.error}"
        return f"子智能体已完成。\nagent_id: {agent_id}\n结果:\n{result.answer}"
