from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from react.action.base import BaseAction


class KnowledgeListArgs(BaseModel):
    domain: str = Field(..., min_length=1, description="领域名称，如 'quantum_computing'")
    limit: int = Field(20, ge=1, le=100, description="最多返回条目数，默认 20")


class KnowledgeListAction(BaseAction):
    name: str = "knowledge_list"
    description: str = (
        "列出本地知识库中某个领域下已保存的概念清单，"
        "用于感知「已知边界」并识别知识空白。"
        "参数：domain（领域名称），limit（最多返回数，默认 20）"
    )
    args_model: ClassVar[type[BaseModel]] = KnowledgeListArgs

    kb: Any = None  # KnowledgeBase，构造时注入

    def execute(self, domain: str, limit: int = 20, **kwargs) -> str:
        if self.kb is None:
            return "知识库未初始化。"

        rows = self.kb.store.list_by_domain(domain, limit=limit)
        if not rows:
            return f"知识库中尚无关于「{domain}」的任何内容。"

        lines = [f"知识库「{domain}」已收录 {len(rows)} 个条目：\n"]
        for i, row in enumerate(rows, 1):
            concept = row.get("concept") or "-"
            title = row.get("title") or ""
            lines.append(f"{i}. 概念: {concept}  标题: {title}")

        return "\n".join(lines)
