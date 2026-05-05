from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from react.action.base import BaseAction


class SpawnAgentArgs(BaseModel):
    instruction: str = Field(..., min_length=1, description="交给子智能体执行的完整指令")
    profile: str = Field(
        "minimal",
        description=(
            "子智能体配置：minimal（默认，通用）| executor（执行型，返回日志）| "
            "researcher（研究/搜索）| researcher_with_memory（研究+L3记忆）| "
            "analyst（分析/计算）"
        ),
    )


class SpawnAgentAction(BaseAction):
    name: str = "spawn_agent"
    description: str = (
        "在后台异步派发一个子智能体执行任务，立即返回 agent_id，无需等待完成。"
        "适合长时任务或需要并行运行多个子任务的场景。"
        "参数：instruction（给子智能体的指令），profile（minimal|researcher|analyst，默认 minimal）。"
        "返回 agent_id，之后可用 get_agent_result(agent_id) 查询结果。"
    )
    args_model: ClassVar[type[BaseModel]] = SpawnAgentArgs

    manager: Any = None  # CrewManager，构造时注入

    def execute(self, instruction: str, profile: str = "minimal", **kwargs) -> str:
        if self.manager is None:
            return "Crew 管理器未初始化。"
        agent_id = self.manager.spawn(instruction, profile)
        return f"子智能体已派发。\nagent_id: {agent_id}\nprofile: {profile}\n使用 get_agent_result 查询结果。"
