from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from ....action.base import BaseAction


class KnowledgeSaveArgs(BaseModel):
    content: str = Field(..., min_length=1, description="要保存的知识内容")
    title: str = Field("", description="标题（可选）")
    domain: str = Field("", description="所属领域，如 'quantum_computing'")
    concept: str = Field("", description="具体概念，如 'superposition'")
    sources: str = Field("", description="来源 URL，多个用逗号分隔")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="置信度，0~1，默认 1.0")


class KnowledgeSaveAction(BaseAction):
    name: str = "knowledge_save"
    description: str = (
        "将知识、洞见或总结保存到本地知识库。"
        "参数：content（内容），title（标题），"
        "domain（领域），concept（概念），"
        "sources（来源URL，逗号分隔），confidence（置信度 0~1）"
    )
    args_model: ClassVar[type[BaseModel]] = KnowledgeSaveArgs

    kb: Any = None  # KnowledgeBase，构造时注入

    def execute(
        self,
        content: str,
        title: str = "",
        domain: str = "",
        concept: str = "",
        sources: str = "",
        confidence: float = 1.0,
        **kwargs,
    ) -> str:
        if self.kb is None:
            return "知识库未初始化。"

        meta: dict = {}
        if domain:
            meta["domain"] = domain
        if concept:
            meta["concept"] = concept
        if sources:
            meta["sources"] = [s.strip() for s in sources.split(",") if s.strip()]
        if confidence != 1.0:
            meta["confidence"] = confidence

        doc_id = self.kb.ingest_text(
            content,
            source="agent_learning",
            source_type="agent_learning",
            title=title or (f"{domain}/{concept}" if domain else "agent_note"),
            meta=meta if meta else None,
        )
        return f"已保存到知识库。doc_id={doc_id}"
