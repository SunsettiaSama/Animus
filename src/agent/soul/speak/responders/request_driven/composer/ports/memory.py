from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

MemoryHint = Literal["share", "random", "related"]
RetrieveMode = Literal["bm25", "embedding", "hybrid", "random"]


@dataclass(frozen=True)
class MemoryUnit:
    """记忆 buffer 的离散单元；可携带 embedding 供向量检索。"""

    unit_id: str
    text: str
    source: str = ""
    score: float = 0.0
    embedding: tuple[float, ...] = ()
    meta: dict[str, object] = field(default_factory=dict, hash=False, compare=False)

    def with_embedding(self, vector: list[float] | tuple[float, ...]) -> MemoryUnit:
        return MemoryUnit(
            unit_id=self.unit_id,
            text=self.text,
            source=self.source,
            score=self.score,
            embedding=tuple(float(x) for x in vector),
            meta=dict(self.meta),
        )


class MemorySearchPort(Protocol):
    def search_related(
        self,
        session_id: str,
        query_text: str,
        *,
        limit: int,
        hint: MemoryHint = "related",
    ) -> list[MemoryUnit]: ...


class NullMemorySearchPort:
    def search_related(
        self,
        session_id: str,
        query_text: str,
        *,
        limit: int,
        hint: MemoryHint = "related",
    ) -> list[MemoryUnit]:
        return []


class BufferEmbedderPort(Protocol):
    """buffer 内向量检索用；兼容 Soul EmbeddingPort.embed。"""

    def embed(self, text: str) -> list[float]: ...
