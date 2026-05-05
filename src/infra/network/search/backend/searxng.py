from __future__ import annotations

import os

from infra.network.search.backend.base import BaseSearchBackend
from infra.network.search.result import SearchResult


class SearXNGBackend(BaseSearchBackend):
    """
    SearXNG HTTP JSON API 后端。

    可用条件（静态判断，不发起网络请求）：
      - 环境变量 SEARXNG_URL 已设置，或
      - 配置中的 url 不是模板占位符（不含 "yourdomain.com"）
    """

    def __init__(self, config) -> None:
        self._cfg = config

    @property
    def name(self) -> str:
        return "searxng"

    def is_available(self) -> bool:
        if os.environ.get("SEARXNG_URL"):
            return True
        return "yourdomain.com" not in self._cfg.url

    def search(
        self,
        query: str,
        max_results: int,
        language: str,
        categories: str,
    ) -> list[SearchResult]:
        import httpx

        transport = httpx.HTTPTransport(retries=self._cfg.request.max_retries)
        params = {
            "q": query,
            "format": "json",
            "categories": categories,
            "language": language,
            "pageno": 1,
            "safesearch": self._cfg.search.safe_search,
        }

        with httpx.Client(transport=transport, verify=self._cfg.ssl_verify) as client:
            resp = client.get(
                f"{self._cfg.effective_url}/search",
                params=params,
                timeout=self._cfg.request.timeout,
                headers=self._cfg.request.headers,
            )

        resp.raise_for_status()
        data = resp.json()
        limit = min(max_results, self._cfg.search.max_results_limit)

        return [
            SearchResult(
                title=r.get("title", "").strip(),
                snippet=r.get("content", "").strip(),
                url=r.get("url", "").strip(),
                engine=r.get("engine", "").strip(),
                score=float(r.get("score", 0.0)),
            )
            for r in data.get("results", [])[:limit]
        ]
