from __future__ import annotations

from react.action.base import BaseAction


def _search(query: str, max_results: int, region: str) -> list[dict]:
    from duckduckgo_search import DDGS
    with DDGS() as ddgs:
        return list(ddgs.text(query, region=region, max_results=max_results))


class WebSearchAction(BaseAction):
    name: str = "web_search"
    description: str = (
        "在互联网上搜索最新信息（使用 DuckDuckGo）。"
        "参数：query（搜索词），max_results（最大结果数，默认3，最多8），"
        "region（地区代码，默认 wt-wt 表示全球，cn-zh 表示中国大陆）"
    )

    def execute(
        self,
        query: str = "",
        max_results: int = 3,
        region: str = "wt-wt",
        **kwargs,
    ) -> str:
        if not query:
            raise ValueError("缺少参数 query")

        max_results = max(1, min(int(max_results), 8))
        results = _search(query.strip(), max_results, region)

        if not results:
            return f"未找到与 {query!r} 相关的搜索结果，请换个关键词重试。"

        lines = [f"搜索「{query}」的结果（共 {len(results)} 条）：\n"]
        for i, r in enumerate(results, 1):
            title   = r.get("title",   "").strip()
            snippet = r.get("body",    "").strip()
            url     = r.get("href",    "").strip()
            lines.append(f"{i}. {title}")
            if snippet:
                lines.append(f"   {snippet}")
            if url:
                lines.append(f"   URL: {url}")
            lines.append("")

        return "\n".join(lines).strip()
