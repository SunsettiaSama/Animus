from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

MemoryHint = Literal["share", "random", "related"]


@dataclass(frozen=True)
class MemoryUnit:
    unit_id: str
    text: str
    source: str = ""
    score: float = 0.0


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
