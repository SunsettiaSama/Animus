from __future__ import annotations

from infra.network.search.backend.base import BaseSearchBackend
from infra.network.search.result import SearchResult

_TAVILY_ENDPOINT = "https://api.tavily.com/search"


class TavilyBackend(BaseSearchBackend):
    """
    Tavily Search API 后端（为 AI Agent 设计的搜索服务）。

    可用条件：环境变量 TAVILY_API_KEY 已设置。
    申请：https://tavily.com
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "tavily"

    def is_available(self) -> bool:
        return bool(self._api_key)

    def search(
        self,
        query: str,
        max_results: int,
        language: str,
        categories: str,
    ) -> list[SearchResult]:
        import httpx

        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": min(max_results, 10),
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        }

        resp = httpx.post(_TAVILY_ENDPOINT, json=payload, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()

        return [
            SearchResult(
                title=r.get("title", "").strip(),
                snippet=r.get("content", "").strip(),
                url=r.get("url", "").strip(),
                engine="tavily",
                score=float(r.get("score", 0.0)),
            )
            for r in data.get("results", [])[:max_results]
        ]
