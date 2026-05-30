from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InteractorSocialPrefetchResult:
    session_id: str
    interactor_id: str
    turn_index: int = 0
    lines: list[str] = field(default_factory=list)
    unit_ids: list[str] = field(default_factory=list)


@dataclass
class KeywordFieldResult:
    session_id: str
    interactor_id: str
    turn_index: int = 0
    lines: list[str] = field(default_factory=list)
    unit_ids: list[str] = field(default_factory=list)


@dataclass
class WarmSpreadResult:
    session_id: str
    lines: list[str] = field(default_factory=list)
    unit_ids: list[str] = field(default_factory=list)
