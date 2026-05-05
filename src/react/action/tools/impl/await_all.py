from __future__ import annotations

import json
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from react.action.base import BaseAction


class AwaitAllArgs(BaseModel):
    agent_ids: str = Field(
        ...,
        description="JSON 数组，包含所有需要等待的 agent_id 字符串",
    )
    timeout: float = Field(300.0, ge=1.0, description="整体最长等待秒数，默认 300 秒")


class AwaitAllAction(BaseAction):
    name: str = "await_all"
    description: str = (
        "等待多个异步子智能体全部完成（Fan-in），返回所有结果摘要。"
        "参数：agent_ids（JSON 数组，含所有 agent_id），timeout（整体超时秒数，默认 300）。"
        "返回每个子智能体的 status 和 answer。"
    )
    args_model: ClassVar[type[BaseModel]] = AwaitAllArgs

    manager: Any = None  # CrewManager，构造时注入

    def execute(self, agent_ids: str, timeout: float = 300.0, **kwargs) -> str:
        if self.manager is None:
            return "Crew 管理器未初始化。"
        ids: list[str] = json.loads(agent_ids)
        if not isinstance(ids, list) or len(ids) == 0:
            return "agent_ids 必须是非空 JSON 数组。"
        results = self.manager.await_all(ids, timeout=timeout)
        lines = [f"全部 {len(results)} 个子智能体已处理：", ""]
        for r in results:
            if r.status == "done":
                preview = r.answer[:200] + "..." if len(r.answer) > 200 else r.answer
                lines.append(f"[done] {r.agent_id[:8]}\n  {preview}")
            elif r.status == "failed":
                lines.append(f"[failed] {r.agent_id[:8]}\n  错误: {r.error}")
            else:
                lines.append(f"[{r.status}] {r.agent_id[:8]}")
        return "\n".join(lines)
