from __future__ import annotations

import os

from infra.network.search.backend.base import BaseSearchBackend
from infra.network.search.backend.ddg import DDGBackend
from infra.network.search.backend.searxng import SearXNGBackend
from infra.network.search.backend.tavily import TavilyBackend
from infra.network.search.result import SearchResult


class SearchEngine:
    """
    网络检索统一调度入口。

    后端优先级（静态判断，不发起网络探测）：
      1. SearXNG  — 设置了 SEARXNG_URL 环境变量，或 yaml 中 url 非占位符
      2. Tavily   — 设置了 TAVILY_API_KEY 环境变量
      3. DDG      — duckduckgo_search 包已安装（零配置回退）

    使用第一个 is_available() 为 True 的后端；若全部不可用则 raise。
    """

    def __init__(self, config=None) -> None:
        from config.network.web_search_config import WebSearchConfig
        self._cfg = config or WebSearchConfig.load()
        self._backends: list[BaseSearchBackend] = [
            SearXNGBackend(self._cfg),
            TavilyBackend(os.environ.get("TAVILY_API_KEY", "")),
            DDGBackend(),
        ]

    _NO_BACKEND_MSG = (
        "没有可用的搜索后端。\n"
        "请至少满足以下之一：\n"
        "  · 设置 SEARXNG_URL 指向运行中的 SearXNG 实例\n"
        "  · 设置 TAVILY_API_KEY（https://tavily.com）\n"
        "  · 安装 duckduckgo_search（pip install duckduckgo-search）"
    )

    # ── 内部 ──────────────────────────────────────────────────────────────────

    def _active_backend(self) -> BaseSearchBackend:
        """返回第一个通过可用性检测（含连通性探测）的后端。"""
        for backend in self._backends:
            if backend.is_available():
                return backend
        raise RuntimeError(self._NO_BACKEND_MSG)

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    @property
    def active_backend_name(self) -> str:
        return self._active_backend().name

    def search(
        self,
        query: str,
        max_results: int = 3,
        language: str = "auto",
        categories: str = "general",
    ) -> list[SearchResult]:
        """按优先级逐一尝试可用后端，失败时自动降级到下一个。"""
        last_exc: Exception | None = None
        for backend in self._backends:
            if not backend.is_available():
                continue
            try:
                return backend.search(query, max_results, language, categories)
            except Exception as exc:
                last_exc = exc
        if last_exc is not None:
            raise RuntimeError(
                f"所有可用后端均失败，最后错误：{last_exc}"
            ) from last_exc
        raise RuntimeError(self._NO_BACKEND_MSG)
