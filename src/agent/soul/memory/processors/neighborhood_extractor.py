from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from agent.soul.life.experience.unit import ExperienceUnit


@dataclass
class NeighborhoodCandidate:
    label: str
    content: str
    related_labels: list[str] = field(default_factory=list)


class NeighborhoodExtractorPort(Protocol):
    def extract(self, unit: ExperienceUnit) -> list[NeighborhoodCandidate]: ...
