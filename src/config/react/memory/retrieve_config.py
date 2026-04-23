from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetrieveConfig:
    light_top_k: int = 3
    light_min_score: float = 0.0
    heavy_top_k: int = 8
    heavy_min_score: float = 0.0
    supplement_top_k: int = 2
    supplement_min_score: float = 0.0
    supplement_context_min_len: int = 30
    profile_top_k: int = 3
    profile_min_score: float = 0.0
    profile_query: str = "user profile background preferences habits"
    timeline_top_k: int = 5

    @classmethod
    def from_dict(cls, d: dict) -> RetrieveConfig:
        return cls(
            light_top_k=int(d.get("light_top_k", 3)),
            light_min_score=float(d.get("light_min_score", 0.0)),
            heavy_top_k=int(d.get("heavy_top_k", 8)),
            heavy_min_score=float(d.get("heavy_min_score", 0.0)),
            supplement_top_k=int(d.get("supplement_top_k", 2)),
            supplement_min_score=float(d.get("supplement_min_score", 0.0)),
            supplement_context_min_len=int(d.get("supplement_context_min_len", 30)),
            profile_top_k=int(d.get("profile_top_k", 3)),
            profile_min_score=float(d.get("profile_min_score", 0.0)),
            profile_query=d.get("profile_query", "user profile background preferences habits"),
            timeline_top_k=int(d.get("timeline_top_k", 5)),
        )
