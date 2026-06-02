from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class StoryEventKind(str, Enum):
    landmark = "landmark"
    surprise = "surprise"
    fabricate = "fabricate"
    wander = "wander"
    speak_cue = "speak_cue"
    snapshot = "snapshot"


@dataclass(frozen=True)
class StatePatch:
    move_to_location_id: str | None = None
    entity_deltas: dict[str, dict] = field(default_factory=dict)
    flags: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "move_to_location_id": self.move_to_location_id,
            "entity_deltas": dict(self.entity_deltas),
            "flags": dict(self.flags),
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> StatePatch:
        if not data:
            return cls()
        return cls(
            move_to_location_id=data.get("move_to_location_id"),
            entity_deltas=dict(data.get("entity_deltas") or {}),
            flags=dict(data.get("flags") or {}),
        )


@dataclass(frozen=True)
class SceneUnit:
    id: str
    world_id: str
    name: str
    narrative: str
    location_id: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SceneEdge:
    id: str
    world_id: str
    from_scene_id: str
    to_scene_id: str
    transition_text: str
    weight: int = 10


@dataclass(frozen=True)
class SceneCandidate:
    scene: SceneUnit
    transition_text: str = ""
    matched_by: str = ""
    score: int = 0


@dataclass(frozen=True)
class SceneLocateResult:
    scene: SceneUnit | None
    transition_text: str = ""
    inject_text: str = ""
    matched_by: str = ""


@dataclass(frozen=True)
class ScenePacket:
    event_id: str
    world_id: str
    scene_text: str
    location_id: str | None = None
    entity_ids: tuple[str, ...] = ()
    lore_refs: tuple[str, ...] = ()
    world_time: str = ""


@dataclass(frozen=True)
class ResolvedOutcome:
    event_id: str
    world_id: str
    resolution_text: str
    dice_value: int = 0
    dice_tendency: str = ""
    deviation: bool = False
    deviation_note: str = ""
    state_patch: StatePatch = field(default_factory=StatePatch)


@dataclass(frozen=True)
class NarrativeBrief:
    hint: str
    profile_narrative: str = ""
    memory_lines: list[str] = field(default_factory=list)
    dice_tendency: str = ""
    query: str = ""


@dataclass(frozen=True)
class StoryBeat:
    text: str
    emotion_label: str = ""
    emotion_intensity: float = 0.45
    chapter_hint: str = ""
