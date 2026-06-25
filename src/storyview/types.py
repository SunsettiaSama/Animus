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


@dataclass(frozen=True)
class GMQuestion:
    question_id: str
    world_id: str
    kind: StoryEventKind | str
    cue: str
    scene_id: str
    question: str
    stakes: str = ""
    choices: tuple[str, ...] = ()
    open_choice: bool = True
    constraints: str = ""
    is_move: bool = False
    move_target_scene_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "world_id": self.world_id,
            "kind": str(getattr(self.kind, "value", self.kind)),
            "cue": self.cue,
            "scene_id": self.scene_id,
            "question": self.question,
            "stakes": self.stakes,
            "choices": list(self.choices),
            "open_choice": self.open_choice,
            "constraints": self.constraints,
            "is_move": self.is_move,
            "move_target_scene_ids": list(self.move_target_scene_ids),
        }

    @classmethod
    def from_dict(cls, data: dict) -> GMQuestion:
        return cls(
            question_id=str(data["question_id"]),
            world_id=str(data["world_id"]),
            kind=data.get("kind", StoryEventKind.fabricate.value),
            cue=str(data.get("cue", "")),
            scene_id=str(data.get("scene_id", "")),
            question=str(data.get("question", "")),
            stakes=str(data.get("stakes", "")),
            choices=tuple(str(x) for x in data.get("choices", ()) or ()),
            open_choice=bool(data.get("open_choice", True)),
            constraints=str(data.get("constraints", "")),
            is_move=bool(data.get("is_move", False)),
            move_target_scene_ids=tuple(
                str(x) for x in data.get("move_target_scene_ids", ()) or ()
            ),
        )


@dataclass(frozen=True)
class GMAnswer:
    question_id: str
    text: str
    intent: str = ""

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "text": self.text,
            "intent": self.intent,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GMAnswer:
        return cls(
            question_id=str(data["question_id"]),
            text=str(data.get("text", "")),
            intent=str(data.get("intent", "")),
        )


@dataclass(frozen=True)
class StoryInfluence:
    salience: float
    emotion_hint: str = ""
    mood_span: str = ""
    linger_days: int = 0
    decision_importance: str = ""

    def to_dict(self) -> dict:
        return {
            "salience": self.salience,
            "emotion_hint": self.emotion_hint,
            "mood_span": self.mood_span,
            "linger_days": self.linger_days,
            "decision_importance": self.decision_importance,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> StoryInfluence:
        if not data:
            return cls(salience=0.5)
        return cls(
            salience=float(data.get("salience", 0.5)),
            emotion_hint=str(data.get("emotion_hint", "")),
            mood_span=str(data.get("mood_span", "")),
            linger_days=int(data.get("linger_days", 0)),
            decision_importance=str(data.get("decision_importance", "")),
        )


@dataclass(frozen=True)
class GMExchange:
    question: GMQuestion
    answer: GMAnswer
    scene_packet: ScenePacket
    resolved: ResolvedOutcome
    kind: str = "beat"


@dataclass(frozen=True)
class StoryBeatOutcome:
    question: GMQuestion
    answer: GMAnswer
    scene_packet: ScenePacket
    resolved: ResolvedOutcome
    dice_value: int = 0
    dice_tendency: str = ""
    influence: StoryInfluence = field(default_factory=lambda: StoryInfluence(salience=0.5))
    scene_candidates: tuple[SceneCandidate, ...] = ()
    arc_steps: tuple[GMExchange, ...] = ()
    objective_summary: str = ""
