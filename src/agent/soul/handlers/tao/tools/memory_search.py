from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from agent.react.action.base import BaseAction


class SoulMemorySearchArgs(BaseModel):
    mode: str = Field(
        "hybrid",
        description=(
            "检索模式：recent / semantic / by_valence / by_field / hybrid（默认）"
        ),
    )
    query: str = Field("", description="检索文本（semantic/hybrid 必填）")
    top_k: int = Field(5, ge=1, le=20, description="最多返回条数")
    valence: str = Field("", description="by_valence/hybrid 可选：positive/negative/mixed/neutral")
    memory_type: str = Field("", description="可选：factual/reconstructive/narrative")
    emotion_hint: str = Field("", description="by_valence 可选情绪关键词")


class SoulMemorySearchAction(BaseAction):
    """经 Soul 接口检索长期/短期记忆（五种模式）。"""

    name: str = "soul_memory_search"
    description: str = (
        "经 Soul 检索记忆。"
        "参数：mode（recent|semantic|by_valence|by_field|hybrid），"
        "query（主题/关键词），top_k（默认 5），"
        "valence（情感倾向，可选），memory_type（可选）。"
    )
    args_model: ClassVar[type[BaseModel]] = SoulMemorySearchArgs

    soul: Any = None

    def execute(
        self,
        mode: str = "hybrid",
        query: str = "",
        top_k: int = 5,
        valence: str = "",
        memory_type: str = "",
        emotion_hint: str = "",
        **kwargs,
    ) -> str:
        if self.soul is None:
            return "Soul Memory 服务未就绪。"
        payload: dict[str, Any] = {"top_k": top_k}
        if query.strip():
            payload["query"] = query.strip()
        if valence.strip():
            payload["valence"] = valence.strip()
        if memory_type.strip():
            payload["memory_type"] = memory_type.strip()
        if emotion_hint.strip():
            payload["emotion_hint"] = emotion_hint.strip()
        m = mode.strip().lower() or "hybrid"
        if m in ("semantic", "hybrid", "smart", "recall") and not payload.get("query"):
            return "semantic/hybrid 模式需要 query 参数。"
        result = self.soul.search_memory(m, **payload)
        rows = result.get("results") or []
        if not rows:
            return "暂无匹配记忆。"
        lines: list[str] = []
        for row in rows:
            focus = row.get("focus", "")
            score = row.get("final_score", 0)
            source = row.get("source", "")
            mtype = row.get("memory_type", "")
            body = (
                row.get("fact")
                or row.get("reconstructed_fact")
                or row.get("narrative")
                or ""
            )
            lines.append(
                f"[{source}/{mtype} score={score:.3f}] {focus}：{str(body)[:120]}"
            )
        return "\n".join(lines)
