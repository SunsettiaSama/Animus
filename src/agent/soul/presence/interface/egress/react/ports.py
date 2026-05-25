from __future__ import annotations

from typing import Protocol


class EmbeddingPort(Protocol):
    """顶层 embedding 服务最小接口。"""

    def embed(self, text: str) -> list[float]: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class ListEmbeddingAdapter:
    """将仅实现 embed() 的后端适配为 EmbeddingPort。"""

    def __init__(self, backend) -> None:
        self._backend = backend

    def embed(self, text: str) -> list[float]:
        return self._backend.embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._backend.embed(text) for text in texts]
