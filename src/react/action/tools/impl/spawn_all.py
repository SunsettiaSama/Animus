from __future__ import annotations

import json
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from react.action.base import BaseAction


class SpawnAllArgs(BaseModel):
    tasks: str = Field(
        ...,
        description=(
            "JSON 数组，每项为 {\"instruction\": \"...\", \"profile\": \"minimal\"} 格式。"
            "profile 可选，默认 minimal；可选值：minimal | executor | researcher | researcher_with_memory | analyst | planner。"
        ),
    )


class SpawnAllAction(BaseAction):
    name: str = "spawn_all"
    description: str = (
        "批量并行派发多个子智能体任务，立即返回所有 agent_id。"
        "适合需要同时执行多个独立子任务（Fan-out）的场景。"
        "参数：tasks（JSON 数组，每项含 instruction 和可选 profile）。"
        "返回 agent_id 列表，之后可用 await_all 等待所有结果。"
    )
    args_model: ClassVar[type[BaseModel]] = SpawnAllArgs

    manager: Any = None  # CrewManager，构造时注入

    def execute(self, tasks: str, **kwargs) -> str:
        if self.manager is None:
            return "Crew 管理器未初始化。"
        task_list = json.loads(tasks)
        if not isinstance(task_list, list) or len(task_list) == 0:
            return "tasks 必须是非空 JSON 数组。"
        agent_ids = self.manager.spawn_all(task_list)
        lines = [f"已并行派发 {len(agent_ids)} 个子智能体："]
        for i, aid in enumerate(agent_ids):
            lines.append(f"  [{i}] agent_id: {aid}")
        lines.append("使用 await_all 等待所有结果。")
        return "\n".join(lines)
