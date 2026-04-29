from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from react.action.base import BaseAction


class KnowledgeHybridSearchArgs(BaseModel):
    query: str = Field(..., min_length=1, description="查询内容，自然语言描述")
    top_k_each: int = Field(3, ge=1, le=20, description="每种检索路径返回的结果数，默认 3")
    mode: str = Field(
        "hybrid",
        description="检索模式：keyword（关键词）/ semantic（语义）/ hybrid（并行混合，默认）",
    )
    doc_id_filter: str = Field("", description="限定文档 ID（可选），仅在 semantic/hybrid 模式下生效")


_MODE_LABEL = {
    "keyword": "[K]",
    "semantic": "[S]",
    "keyword_fts": "[K]",
    "fallback_fts": "[K]",
    "qdrant_payload": "[S]",
    "mysql": "[S]",
}


class KnowledgeHybridSearchAction(BaseAction):
    name: str = "knowledge_hybrid_search"
    description: str = (
        "在本地知识库中进行混合检索，支持三种模式：\n"
        "  keyword  — 仅关键词全文检索（MySQL FULLTEXT）\n"
        "  semantic — 仅语义向量检索（Qdrant + MySQL）\n"
        "  hybrid   — 二者并行，去重后合并（默认）\n"
        "参数：query（查询内容），top_k_each（每路径返回数，默认 3），"
        "mode（keyword/semantic/hybrid），doc_id_filter（限定文档 ID，可选）"
    )
    args_model: ClassVar[type[BaseModel]] = KnowledgeHybridSearchArgs

    kb: Any = None  # KnowledgeBase，构造时注入

    def execute(
        self,
        query: str,
        top_k_each: int = 3,
        mode: str = "hybrid",
        doc_id_filter: str = "",
        **kwargs,
    ) -> str:
        if self.kb is None:
            return "知识库未初始化。"

        doc_filter = doc_id_filter.strip() or None

        if mode == "keyword":
            results = self.kb.search_keyword(query, top_k=top_k_each)
            header = f"关键词检索「{query}」结果（共 {len(results)} 条）："
        elif mode == "semantic":
            results = self.kb.search_semantic(query, top_k=top_k_each, doc_id_filter=doc_filter)
            header = f"语义检索「{query}」结果（共 {len(results)} 条）："
        elif mode == "hybrid":
            results = self.kb.hybrid_search(
                query, top_k_each=top_k_each, doc_id_filter=doc_filter
            )
            kw_count = sum(1 for r in results if r.source in ("keyword_fts", "fallback_fts"))
            sem_count = len(results) - kw_count
            header = (
                f"混合检索「{query}」结果"
                f"（keyword: {kw_count} 条 | semantic: {sem_count} 条）："
            )
        else:
            return f"不支持的检索模式「{mode}」，请使用 keyword / semantic / hybrid。"

        if not results:
            return f"知识库中未找到与「{query}」相关的内容。"

        lines = [header, ""]
        for i, r in enumerate(results, 1):
            label = _MODE_LABEL.get(r.source, "[?]")
            score_str = f" | score: {r.score:.3f}" if r.score > 0 else ""
            lines.append(f"{label} {i}. [{r.source}{score_str}]")
            lines.append(f"   {r.content[:500]}")
            if r.meta.get("domain"):
                lines.append(
                    f"   领域: {r.meta['domain']} / 概念: {r.meta.get('concept', '-')}"
                )
            lines.append("")

        return "\n".join(lines).strip()
