from __future__ import annotations

import os
import socket
from urllib.parse import urlparse

from infra.network.search.backend.base import BaseSearchBackend
from infra.network.search.result import SearchResult


class SearXNGBackend(BaseSearchBackend):
    """
    SearXNG HTTP JSON API 后端。

    可用条件（TCP 连通性探测，超时 1 秒）：
      - URL 不是模板占位符（不含 "yourdomain.com"），且
      - 目标主机:端口 TCP 可达
    """

    def __init__(self, config) -> None:
        self._cfg = config

    @property
    def name(self) -> str:
        return "searxng"

    def is_available(self) -> bool:
        url = self._cfg.effective_url
        if "yourdomain.com" in url:
            return False
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex((host, port)) == 0

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
