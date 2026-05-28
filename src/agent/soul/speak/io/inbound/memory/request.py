from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RecallRequest:
    session_id: str
    query: str
    top_k: int | None = None


@dataclass
class RecallResult:
    ok: bool
    query: str = ""
    text: str = ""
    reason: str = ""


@dataclass(frozen=True)
class PointQueryRequest:
    session_id: str
    interactor_id: str
    turn_index: int
    user_text: str
    agent_text: str = ""


@dataclass
class SimilarMemoryBlock:
    turn_index: int
    lines: list[str] = field(default_factory=list)
    unit_ids: list[str] = field(default_factory=list)


@dataclass
class SimilarMemoryPullResult:
    inject: SimilarMemoryBlock = field(default_factory=SimilarMemoryBlock)
    spilled: SimilarMemoryBlock = field(default_factory=SimilarMemoryBlock)
