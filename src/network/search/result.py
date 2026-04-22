from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SearchResult:
    title: str
    snippet: str
    url: str
    engine: str = ""
    score: float = 0.0
    extra: dict = field(default_factory=dict)
