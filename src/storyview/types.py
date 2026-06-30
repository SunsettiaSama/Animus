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


class ArcStartPolicy(str, Enum):
    history = "history"
    home = "home"


class LocationSnapshotReason(str, Enum):
    arc_start = "arc_start"
    gm_answer = "gm_answer"
    move = "move"
    manual_apply = "manual_apply"
    home_reset = "home_reset"


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
class SceneCard:
    id: str
    title: str
    description: str
    affordances: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "affordances": list(self.affordances),
            "conditions": list(self.conditions),
            "entities": list(self.entities),
        }

    @classmethod
    def from_dict(cls, data: dict) -> SceneCard:
        affordances_raw = data.get("affordances")
        if affordances_raw is None:
            affordances_raw = data.get("affordance") or []
        if isinstance(affordances_raw, str):
            affordances_raw = [affordances_raw]
        conditions_raw = data.get("conditions") or []
        if isinstance(conditions_raw, str):
            conditions_raw = [conditions_raw]
        entities_raw = data.get("entities") or []
        if isinstance(entities_raw, str):
            entities_raw = [entities_raw]
        return cls(
            id=str(data.get("id", "")).strip(),
            title=str(data.get("title", "")).strip(),
            description=str(
                data.get("description")
                or data.get("narrative")
                or data.get("summary")
                or ""
            ).strip(),
            affordances=tuple(
                str(item).strip() for item in affordances_raw if str(item).strip()
            ),
            conditions=tuple(
                str(item).strip() for item in conditions_raw if str(item).strip()
            ),
            entities=tuple(
                str(item).strip() for item in entities_raw if str(item).strip()
            ),
        )


@dataclass(frozen=True)
class SceneUnit:
    id: str
    world_id: str
    name: str
    narrative: str
    location_id: str | None = None
    tags: tuple[str, ...] = ()
    meta: dict = field(default_factory=dict)


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
    story_direction: str = ""
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


class SceneReviewStatus(str, Enum):
    approved = "approved"
    revision_required = "revision_required"
    rejected = "rejected"


@dataclass(frozen=True)
class SceneDraft:
    name: str
    narrative: str
    location_hint: str = ""
    tags: tuple[str, ...] = ()
    cards: tuple[SceneCard, ...] = ()
    edges: tuple[str, ...] = ()
    node_mutations: tuple[SceneNodeMutation, ...] = ()
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "narrative": self.narrative,
            "location_hint": self.location_hint,
            "tags": list(self.tags),
            "cards": [card.to_dict() for card in self.cards],
            "edges": list(self.edges),
            "node_mutations": [mutation.to_dict() for mutation in self.node_mutations],
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SceneDraft:
        data = _unwrap_scene_draft_payload(data)
        cards_raw = data.get("cards") or []
        cards = tuple(
            SceneCard.from_dict(item) for item in cards_raw if isinstance(item, dict)
        )
        mutations_raw = data.get("node_mutations") or []
        mutations = tuple(
            SceneNodeMutation.from_dict(item)
            for item in mutations_raw
            if isinstance(item, dict)
        )
        name = (
            data.get("name")
            or data.get("scene_name")
            or data.get("scene_title")
            or data.get("title")
            or ""
        )
        narrative = (
            data.get("narrative")
            or data.get("scene_summary")
            or data.get("summary")
            or data.get("description")
            or ""
        )
        return cls(
            name=str(name).strip(),
            narrative=str(narrative).strip(),
            location_hint=str(data.get("location_hint") or data.get("location") or "").strip(),
            tags=tuple(str(item).strip() for item in data.get("tags", []) if str(item).strip()),
            cards=cards,
            edges=tuple(str(item).strip() for item in data.get("edges", []) if str(item).strip()),
            node_mutations=mutations,
            reasoning=str(data.get("reasoning", "")).strip(),
        )


def _unwrap_scene_draft_payload(data: dict) -> dict:
    payload = data
    outer_reasoning = str(payload.get("reasoning", "")).strip()
    for key in ("draft", "output", "scene_draft", "approved_draft"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            payload = nested
    if outer_reasoning and not str(payload.get("reasoning", "")).strip():
        payload = dict(payload)
        payload["reasoning"] = outer_reasoning
    return payload


@dataclass(frozen=True)
class SceneNodeMutation:
    scene_id: str
    action: str
    reason: str = ""
    narrative: str = ""
    tags: tuple[str, ...] = ()
    cards: tuple[SceneCard, ...] = ()
    card_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "scene_id": self.scene_id,
            "action": self.action,
            "reason": self.reason,
            "narrative": self.narrative,
            "tags": list(self.tags),
            "cards": [card.to_dict() for card in self.cards],
            "card_ids": list(self.card_ids),
        }

    @classmethod
    def from_dict(cls, data: dict) -> SceneNodeMutation:
        cards_raw = data.get("cards") or []
        return cls(
            scene_id=str(data.get("scene_id", "")).strip(),
            action=str(data.get("action", "")).strip(),
            reason=str(data.get("reason", "")).strip(),
            narrative=str(data.get("narrative", "")).strip(),
            tags=tuple(str(item).strip() for item in data.get("tags", []) if str(item).strip()),
            cards=tuple(
                SceneCard.from_dict(item) for item in cards_raw if isinstance(item, dict)
            ),
            card_ids=tuple(
                str(item).strip() for item in data.get("card_ids", []) if str(item).strip()
            ),
        )


@dataclass(frozen=True)
class SceneReviewPatch:
    field: str
    value: str = ""
    items: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "value": self.value,
            "items": list(self.items),
        }

    @classmethod
    def from_dict(cls, data: dict) -> SceneReviewPatch:
        raw_items = data.get("items", [])
        raw_value = data.get("value", "")
        if not raw_items and isinstance(raw_value, list):
            raw_items = raw_value
            raw_value = ""
        return cls(
            field=str(data.get("field", "")).strip(),
            value=str(raw_value).strip(),
            items=tuple(str(item).strip() for item in raw_items if str(item).strip()),
        )


@dataclass(frozen=True)
class SceneReviewResult:
    status: SceneReviewStatus | str
    reason: str = ""
    patches: tuple[SceneReviewPatch, ...] = ()
    approved_draft: SceneDraft | None = None

    @property
    def is_approved(self) -> bool:
        token = str(getattr(self.status, "value", self.status)).strip().lower()
        return token == SceneReviewStatus.approved.value


@dataclass(frozen=True)
class SceneGroundingPolicy:
    allow_create: bool = True
    match_threshold: int = 4
    max_review_rounds: int = 3
    attach_to_current: bool = True
    allow_node_mutation: bool = False


@dataclass(frozen=True)
class SceneGroundingTraceEntry:
    round: int
    action: str
    observation: str

    def to_dict(self) -> dict:
        return {
            "round": self.round,
            "action": self.action,
            "observation": self.observation,
        }


@dataclass(frozen=True)
class SceneGroundingResult:
    scene_id: str
    scene_name: str
    matched_by: str = ""
    score: int = 0
    created: bool = False
    cards: tuple[SceneCard, ...] = ()
    trace: tuple[SceneGroundingTraceEntry, ...] = ()
    blocked_reason: str = ""
    narrative: str = ""

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_reason.strip()) and not self.scene_id.strip()


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
    dice_value: int = 0
    dice_tendency: str = ""
    story_direction: str = ""
    decision_importance: str = ""


@dataclass(frozen=True)
class AgentLocationSnapshot:
    snapshot_id: str
    world_id: str
    scene_id: str
    scene_text: str
    location_id: str | None = None
    reason: LocationSnapshotReason | str = LocationSnapshotReason.arc_start
    source_event_id: str = ""
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "world_id": self.world_id,
            "scene_id": self.scene_id,
            "scene_text": self.scene_text,
            "location_id": self.location_id,
            "reason": str(getattr(self.reason, "value", self.reason)),
            "source_event_id": self.source_event_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AgentLocationSnapshot:
        return cls(
            snapshot_id=str(data.get("snapshot_id", "")),
            world_id=str(data.get("world_id", "")),
            scene_id=str(data.get("scene_id", "")),
            scene_text=str(data.get("scene_text", "")),
            location_id=data.get("location_id"),
            reason=data.get("reason", LocationSnapshotReason.arc_start.value),
            source_event_id=str(data.get("source_event_id", "")),
            created_at=str(data.get("created_at", "")),
        )


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
