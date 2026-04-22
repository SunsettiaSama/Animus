from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from react.action.base import BaseAction


class WebSearchArgs(BaseModel):
    query: str = Field(..., min_length=1, description="搜索关键词")
    max_results: int = Field(3, ge=1, le=8, description="最大结果数，1~8")
    language: str = Field("auto", description="语言代码，如 'zh-CN'、'en-US'，默认 'auto'")
    categories: str = Field("general", description="搜索类别，如 'general'、'news'、'images'")


class WebSearchAction(BaseAction):
    name: str = "web_search"
    description: str = (
        "在互联网上搜索最新信息。"
        "参数：query（搜索词），max_results（最大结果数，默认3，最多8），"
        "language（语言代码，默认 auto），categories（搜索类别，默认 general）"
    )
    args_model: ClassVar[type[BaseModel]] = WebSearchArgs

    def execute(
        self,
        query: str,
        max_results: int = 3,
        language: str = "auto",
        categories: str = "general",
        **kwargs,
    ) -> str:
        from network.search import SearchEngine, SearchResult

        results: list[SearchResult] = SearchEngine().search(
            query.strip(), max_results, language, categories
        )

        if not results:
            return f"未找到与 {query!r} 相关的搜索结果，请换个关键词重试。"

        lines = [f"搜索「{query}」的结果（共 {len(results)} 条）：\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.title}")
            if r.snippet:
                lines.append(f"   {r.snippet}")
            if r.url:
                lines.append(f"   URL: {r.url}")
            if r.engine:
                lines.append(f"   来源引擎: {r.engine}")
            lines.append("")

        return "\n".join(lines).strip()
