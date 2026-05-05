from __future__ import annotations

from abc import ABC, abstractmethod

from infra.network.search.result import SearchResult


class BaseSearchBackend(ABC):

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def search(
        self,
        query: str,
        max_results: int,
        language: str,
        categories: str,
    ) -> list[SearchResult]: ...

    def is_available(self) -> bool:
        """静态可用性判断（不发起网络请求）。子类按需覆写。"""
        return True
