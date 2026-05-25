from __future__ import annotations

from dataclasses import dataclass, field

from .event import RuminationSignal


@dataclass
class RuminationRefreshResult:
    session_id: str
    applied: bool
    source: str = "fallback"
    narratives: dict[str, str] = field(default_factory=dict)
    reason: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class RuminationIngestResult:
    session_id: str
    rumination: RuminationSignal
    applied: bool
    refresh: RuminationRefreshResult | None = None
    notes: list[str] = field(default_factory=list)
