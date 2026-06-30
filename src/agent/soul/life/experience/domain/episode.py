from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum


def _uid() -> str:
    return str(uuid.uuid4())


class EpisodeItemType(str, Enum):
    episode = "episode"
    arc_step = "arc_step"
    observation = "observation"
    subjective_reaction = "subjective_reaction"
    lesson_or_hypothesis = "lesson_or_hypothesis"


@dataclass
class ArcStepEvidence:
    step_index: int
    gm_question: str = ""
    soul_answer: str = ""
    objective_result: str = ""
    scene_id: str = ""
    scene_text: str = ""
    dice_value: int = 0
    dice_tendency: str = ""
    story_direction: str = ""
    decision_importance: str = ""
    subjective_reaction: str = ""

    def to_dict(self) -> dict:
        return {
            "step_index": self.step_index,
            "gm_question": self.gm_question,
            "soul_answer": self.soul_answer,
            "objective_result": self.objective_result,
            "scene_id": self.scene_id,
            "scene_text": self.scene_text,
            "dice_value": self.dice_value,
            "dice_tendency": self.dice_tendency,
            "story_direction": self.story_direction,
            "decision_importance": self.decision_importance,
            "subjective_reaction": self.subjective_reaction,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ArcStepEvidence:
        return cls(
            step_index=int(data.get("step_index", 0)),
            gm_question=str(data.get("gm_question", "")),
            soul_answer=str(data.get("soul_answer", "")),
            objective_result=str(data.get("objective_result", "")),
            scene_id=str(data.get("scene_id", "")),
            scene_text=str(data.get("scene_text", "")),
            dice_value=int(data.get("dice_value", 0)),
            dice_tendency=str(data.get("dice_tendency", "")),
            story_direction=str(data.get("story_direction", "")),
            decision_importance=str(data.get("decision_importance", "")),
            subjective_reaction=str(data.get("subjective_reaction", "")),
        )


@dataclass
class TypedMemoryItemDraft:
    item_id: str
    item_type: EpisodeItemType
    text: str
    focus: str = ""
    step_index: int = 0
    scene_id: str = ""
    is_hypothesis: bool = False
    source_arc_step: int = 0
    rejection_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "item_type": self.item_type.value,
            "text": self.text,
            "focus": self.focus,
            "step_index": self.step_index,
            "scene_id": self.scene_id,
            "is_hypothesis": self.is_hypothesis,
            "source_arc_step": self.source_arc_step,
            "rejection_reason": self.rejection_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TypedMemoryItemDraft:
        return cls(
            item_id=str(data.get("item_id", _uid())),
            item_type=EpisodeItemType(str(data.get("item_type", EpisodeItemType.observation.value))),
            text=str(data.get("text", "")),
            focus=str(data.get("focus", "")),
            step_index=int(data.get("step_index", 0)),
            scene_id=str(data.get("scene_id", "")),
            is_hypothesis=bool(data.get("is_hypothesis", False)),
            source_arc_step=int(data.get("source_arc_step", 0)),
            rejection_reason=str(data.get("rejection_reason", "")),
        )


@dataclass
class LandmarkEpisode:
    episode_id: str
    experience_id: str = ""
    landmark_id: str = ""
    intention: str = ""
    context: str = ""
    scene_id: str = ""
    scene_name: str = ""
    scene_text: str = ""
    objective_summary: str = ""
    subjective_journal: str = ""
    scene_cards: list[dict] = field(default_factory=list)
    arc_steps: list[ArcStepEvidence] = field(default_factory=list)
    agent_lessons_or_questions: list[str] = field(default_factory=list)
    typed_memory_items: list[TypedMemoryItemDraft] = field(default_factory=list)
    rejected_items: list[TypedMemoryItemDraft] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "episode_id": self.episode_id,
            "experience_id": self.experience_id,
            "landmark_id": self.landmark_id,
            "intention": self.intention,
            "context": self.context,
            "scene_id": self.scene_id,
            "scene_name": self.scene_name,
            "scene_text": self.scene_text,
            "objective_summary": self.objective_summary,
            "subjective_journal": self.subjective_journal,
            "scene_cards": list(self.scene_cards),
            "arc_steps": [step.to_dict() for step in self.arc_steps],
            "agent_lessons_or_questions": list(self.agent_lessons_or_questions),
            "typed_memory_items": [item.to_dict() for item in self.typed_memory_items],
            "rejected_items": [item.to_dict() for item in self.rejected_items],
        }

    @classmethod
    def from_dict(cls, data: dict) -> LandmarkEpisode:
        return cls(
            episode_id=str(data.get("episode_id", _uid())),
            experience_id=str(data.get("experience_id", "")),
            landmark_id=str(data.get("landmark_id", "")),
            intention=str(data.get("intention", "")),
            context=str(data.get("context", "")),
            scene_id=str(data.get("scene_id", "")),
            scene_name=str(data.get("scene_name", "")),
            scene_text=str(data.get("scene_text", "")),
            objective_summary=str(data.get("objective_summary", "")),
            subjective_journal=str(data.get("subjective_journal", "")),
            scene_cards=list(data.get("scene_cards") or []),
            arc_steps=[ArcStepEvidence.from_dict(item) for item in (data.get("arc_steps") or [])],
            agent_lessons_or_questions=list(data.get("agent_lessons_or_questions") or []),
            typed_memory_items=[
                TypedMemoryItemDraft.from_dict(item)
                for item in (data.get("typed_memory_items") or [])
            ],
            rejected_items=[
                TypedMemoryItemDraft.from_dict(item)
                for item in (data.get("rejected_items") or [])
            ],
        )

    def dice_trace(self) -> list[dict]:
        return [
            {
                "step_index": step.step_index,
                "dice_value": step.dice_value,
                "dice_tendency": step.dice_tendency,
                "story_direction": step.story_direction,
                "decision_importance": step.decision_importance,
                "objective_result": step.objective_result,
            }
            for step in self.arc_steps
        ]

    def summary_text(self) -> str:
        parts = [
            self.intention.strip(),
            self.objective_summary.strip(),
        ]
        return " ".join(part for part in parts if part)
