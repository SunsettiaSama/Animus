from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from .agenda.item import LandmarkAgenda, LandmarkAgendaRevision


class LandmarkPlanningStrategy(str, Enum):
    legacy = "legacy"
    agenda_draft = "agenda_draft"
    agenda_story_preview = "agenda_story_preview"


class MemoryRecallPort(Protocol):
    def recall(self, query: str) -> list[str]:
        ...


class JournalLookupPort(Protocol):
    def recent_done(self, *, limit: int = 5) -> list[str]:
        ...

    def digest(self, *, days: int = 7) -> str:
        ...

    def all_intents(self) -> list[str]:
        ...


class ChronicleLookupPort(Protocol):
    def recent_entries(self, *, tail: int = 20) -> list[str]:
        ...

    def hot_experiences(self, *, hours: int = 48) -> list[str]:
        ...


@dataclass(frozen=True)
class LegacyLandmarkComposeResult:
    intention: str
    context: str


@dataclass(frozen=True)
class LandmarkAgendaDraftResult:
    agenda: LandmarkAgenda
    revision_trace: list[LandmarkAgendaRevision] = field(default_factory=list)


@dataclass(frozen=True)
class LandmarkAgendaPreviewResult:
    agenda: LandmarkAgenda
    public_cue: str
    question: str = ""
    answer: str = ""
    revision_trace: list[LandmarkAgendaRevision] = field(default_factory=list)


LandmarkPlanningResult = (
    LegacyLandmarkComposeResult | LandmarkAgendaDraftResult | LandmarkAgendaPreviewResult | None
)
