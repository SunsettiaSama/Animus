from __future__ import annotations

from dataclasses import dataclass, field

from .event import IncidentKind, LifeIncident


@dataclass
class IncidentRefreshResult:
    session_id: str
    kind: IncidentKind
    applied: bool
    source: str = "fallback"
    narratives: dict[str, str] = field(default_factory=dict)
    reason: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class IncidentIngestResult:
    session_id: str
    incident: LifeIncident
    applied: bool
    refresh: IncidentRefreshResult | None = None
    notes: list[str] = field(default_factory=list)
