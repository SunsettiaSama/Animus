from __future__ import annotations

import importlib.util

from network.search.backend.base import BaseSearchBackend
from network.search.result import SearchResult


class DDGBackend(BaseSearchBackend):
    """
    DuckDuckGo 零配置回退后端（需安装 duckduckgo_search）。

    无需 API Key，但受 DDG 速率限制，仅用于开发/测试场景。
    可用条件：duckduckgo_search 包已安装。
    """

    @property
    def name(self) -> str:
        return "duckduckgo"

    def is_available(self) -> bool:
        return importlib.util.find_spec("duckduckgo_search") is not None

    def search(
        self,
        query: str,
        max_results: int,
        language: str,
        categories: str,
    ) -> list[SearchResult]:
        import time
        import warnings
        from duckduckgo_search import DDGS

        # duckduckgo_search v8 在 text() 内部硬编码 backends = ["bing"]，
        # 导致无论传入什么 backend 参数都走 Bing，而 Bing 解析在当前版本返回空列表。
        # _text_lite() 直接调用工作正常，绕开 text() 的派发逻辑。
        time.sleep(1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            ddgs = DDGS()

        region = None if language in ("auto", "") else language
        raw = ddgs._text_lite(query, region=region, max_results=max_results)

        return [
            SearchResult(
                title=r.get("title", "").strip(),
                snippet=r.get("body", "").strip(),
                url=r.get("href", "").strip(),
                engine="duckduckgo",
            )
            for r in raw
        ]
