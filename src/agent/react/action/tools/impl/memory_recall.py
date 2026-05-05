from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from ....action.base import BaseAction

if TYPE_CHECKING:
    from ....memory.long_term.memory import LongTermMemory
    from ....memory.milestone.memory import MilestoneMemory


class MemoryRecallArgs(BaseModel):
    query: str = Field(..., min_length=1, description="回忆的关键词或主题描述")
    top_k: int = Field(5, ge=1, le=20, description="时间线模式下返回的最近条数，默认 5")
    mode: str = Field(
        "smart",
        description=(
            "召回模式："
            "smart（智能，自动选择，默认）/ "
            "semantic（纯语义相似度）/ "
            "timeline（按时间倒序最近 N 条）/ "
            "milestone（仅查里程碑记忆）"
        ),
    )


class MemoryRecallAction(BaseAction):
    """主动记忆召回工具：让 Agent 在推理过程中按需查询长期记忆与里程碑记忆。"""

    name: str = "memory_recall"
    description: str = (
        "主动回忆长期记忆中的内容。"
        "参数：query（回忆的关键词或主题），"
        "top_k（时间线模式下最多返回条数，默认 5），"
        "mode（smart/semantic/timeline/milestone，默认 smart）"
    )
    args_model: ClassVar[type[BaseModel]] = MemoryRecallArgs

    long_term: Any = None    # LongTermMemory | None，构造时注入
    milestone: Any = None    # MilestoneMemory | None，构造时注入

    def execute(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "smart",
        **kwargs,
    ) -> str:
        parts: list[str] = []

        if self.long_term is not None and mode != "milestone":
            if mode == "timeline":
                text = self.long_term.recall_timeline(top_k)
            elif mode == "semantic":
                text = self.long_term.recall(query)
            else:
                text = self.long_term.smart_recall(query)
            if text:
                parts.append(f"【长期记忆】\n{text}")

        if self.milestone is not None and mode in ("smart", "milestone"):
            text = self.milestone.retrieve(query)
            if text:
                parts.append(f"【里程碑记忆】\n{text}")

        if not parts:
            return "暂无与该查询相关的记忆内容。"

        return "\n\n".join(parts)
