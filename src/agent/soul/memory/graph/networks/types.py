from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from agent.soul.memory.graph.base_node import BaseNode


class ExperienceKind(str, Enum):
    """Life ?????????????"""

    anchor = "anchor"
    event = "event"


@dataclass(frozen=True)
class ExperienceBlock:
    """? Life ????????????"""

    experience_id: str
    source: str
    kind: ExperienceKind
    interactor_id: str
    raw_text: str
    emotion_label: str
    salience: float
    valence_delta: float


@dataclass
class SemanticCandidate:
    node_id: str
    score: float
    render: str


@dataclass
class ArchivePlacement:
    focus: str
    subjective_statement: str
    parent_node_id: str | None
    parent_reason: str
    emotion: str
    emotion_intensity: float
    valence: str
    base_activation: float
    label: str = ""


@dataclass
class ArchiveResult:
    node: BaseNode
    parent_node_id: str | None = None
    parent_reason: str = ""
    candidates: list[SemanticCandidate] = field(default_factory=list)
