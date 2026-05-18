from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from ....action.base import BaseAction

if TYPE_CHECKING:
    from agent.soul.memory.long_term.memory import LongTermMemory
    from agent.soul.memory.service import MemoryService


class MemoryRecallArgs(BaseModel):
    query: str = Field(..., min_length=1, description="回忆的关键词或主题描述")
    top_k: int = Field(5, ge=1, le=20, description="最多返回的记忆条数，默认 5")
    mode: str = Field(
        "smart",
        description=(
            "召回模式："
            "smart（智能，默认）/ "
            "semantic（纯语义相似度）/ "
            "timeline（按时间倒序最近 N 条）"
        ),
    )


class MemoryRecallAction(BaseAction):
    """主动记忆召回工具：让 Agent 在推理过程中按需查询记忆。

    优先使用 soul_memory（MemoryService）；
    若未注入，则退回旧的 long_term 实现。
    """

    name: str = "memory_recall"
    description: str = (
        "主动回忆记忆中的内容。"
        "参数：query（回忆的关键词或主题），"
        "top_k（最多返回条数，默认 5），"
        "mode（smart/semantic/timeline，默认 smart）"
    )
    args_model: ClassVar[type[BaseModel]] = MemoryRecallArgs

    soul_memory: Any = None  # MemoryService | None
    long_term: Any = None    # LongTermMemory | None（旧接口）

    def execute(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "smart",
        **kwargs,
    ) -> str:
        if self.soul_memory is not None:
            block = self.soul_memory.recall(query=query, top_k=top_k)
            return block.render() if not block.is_empty() else "暂无与该查询相关的记忆内容。"

        if self.long_term is None:
            return "暂无与该查询相关的记忆内容。"

        if mode == "timeline":
            text = self.long_term.recall_timeline(top_k)
        elif mode == "semantic":
            text = self.long_term.recall(query)
        else:
            text = self.long_term.smart_recall(query)
        if text:
            return f"【长期记忆】\n{text}"
        return "暂无与该查询相关的记忆内容。"
