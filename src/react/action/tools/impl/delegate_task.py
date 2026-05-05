from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from react.action.base import BaseAction


class DelegateTaskArgs(BaseModel):
    instruction: str = Field(..., min_length=1, description="交给 Crew Agent 执行的完整指令")
    profile: str = Field(
        "minimal",
        description=(
            "Agent 配置：minimal（默认，通用）| executor（执行型，返回日志）| "
            "researcher（研究/搜索）| researcher_with_memory（研究+L3记忆）| "
            "analyst（分析/计算）| planner（编排/规划，可递归派发子任务）"
        ),
    )


class DelegateTaskAction(BaseAction):
    name: str = "delegate_task"
    description: str = (
        "将一个具体任务委派给 Crew Agent 同步执行，等待其完成后返回结果。"
        "适合需要即时结果的单次委派。planner profile 可进一步拆解任务并派发给多个 worker。"
        "参数：instruction（给 Agent 的指令），profile（minimal|researcher|analyst|planner，默认 minimal）。"
        "返回 Agent 的最终答案及执行日志。"
    )
    args_model: ClassVar[type[BaseModel]] = DelegateTaskArgs

    manager: Any = None  # CrewManager，构造时注入

    def execute(self, instruction: str, profile: str = "minimal", **kwargs) -> str:
        if self.manager is None:
            return "Crew 管理器未初始化。"
        result = self.manager.delegate(instruction, profile)
        if not result.log:
            return result.answer
        log_lines = result.log[:10]
        log_text = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(log_lines))
        return f"[Crew 任务完成]\n答案：{result.answer}\n执行日志：\n{log_text}"
