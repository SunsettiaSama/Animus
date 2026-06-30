from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from storyview.types import SceneCard, SceneGroundingTraceEntry


class LandmarkAgendaStatus(str, Enum):
    draft = "draft"
    finalized = "finalized"
    completed = "completed"
    archived = "archived"


@dataclass
class LandmarkAgendaRevision:
    round: int
    thought: str
    action: str
    observation: str
    patch_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "round": self.round,
            "thought": self.thought,
            "action": self.action,
            "observation": self.observation,
            "patch_summary": self.patch_summary,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> LandmarkAgendaRevision:
        return cls(
            round=int(raw.get("round", 0)),
            thought=str(raw.get("thought", "")).strip(),
            action=str(raw.get("action", "")).strip(),
            observation=str(raw.get("observation", "")).strip(),
            patch_summary=str(raw.get("patch_summary", "")).strip(),
        )


@dataclass
class LandmarkAgenda:
    id: str
    created_at: str
    target_date: str
    status: LandmarkAgendaStatus
    title: str
    summary: str
    full_context: str
    scene_hint: str = ""
    scene_id: str = ""
    scene_name: str = ""
    scene_cards: list[SceneCard] = field(default_factory=list)
    grounding_trace: list[SceneGroundingTraceEntry] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    memory_refs: list[str] = field(default_factory=list)
    journal_refs: list[str] = field(default_factory=list)
    revision_trace: list[LandmarkAgendaRevision] = field(default_factory=list)

    @classmethod
    def new_draft(
        cls,
        *,
        target_date: str,
        title: str,
        summary: str,
        full_context: str,
    ) -> LandmarkAgenda:
        return cls(
            id=str(uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(),
            target_date=target_date.strip(),
            status=LandmarkAgendaStatus.draft,
            title=title.strip(),
            summary=summary.strip(),
            full_context=full_context.strip(),
        )

    def mark_finalized(self) -> None:
        self.status = LandmarkAgendaStatus.finalized

    def mark_completed(self) -> None:
        self.status = LandmarkAgendaStatus.completed

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "target_date": self.target_date,
            "status": self.status.value,
            "title": self.title,
            "summary": self.summary,
            "full_context": self.full_context,
            "scene_hint": self.scene_hint,
            "scene_id": self.scene_id,
            "scene_name": self.scene_name,
            "scene_cards": [card.to_dict() for card in self.scene_cards],
            "grounding_trace": [item.to_dict() for item in self.grounding_trace],
            "steps": list(self.steps),
            "success_criteria": list(self.success_criteria),
            "constraints": list(self.constraints),
            "memory_refs": list(self.memory_refs),
            "journal_refs": list(self.journal_refs),
            "revision_trace": [item.to_dict() for item in self.revision_trace],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> LandmarkAgenda:
        status_raw = str(raw.get("status", LandmarkAgendaStatus.draft.value)).strip()
        status = LandmarkAgendaStatus(status_raw)
        trace_raw = raw.get("revision_trace", [])
        trace = [
            LandmarkAgendaRevision.from_dict(item)
            for item in trace_raw
            if isinstance(item, dict)
        ]
        return cls(
            id=str(raw.get("id", "")).strip() or str(uuid4()),
            created_at=str(raw.get("created_at", "")).strip()
            or datetime.now(timezone.utc).isoformat(),
            target_date=str(raw.get("target_date", "")).strip(),
            status=status,
            title=str(raw.get("title", "")).strip(),
            summary=str(raw.get("summary", "")).strip(),
            full_context=str(raw.get("full_context", "")).strip(),
            scene_hint=str(raw.get("scene_hint", "")).strip(),
            scene_id=str(raw.get("scene_id", "")).strip(),
            scene_name=str(raw.get("scene_name", "")).strip(),
            scene_cards=[
                SceneCard.from_dict(item)
                for item in raw.get("scene_cards", [])
                if isinstance(item, dict)
            ],
            grounding_trace=[
                SceneGroundingTraceEntry(
                    round=int(item.get("round", 0)),
                    action=str(item.get("action", "")).strip(),
                    observation=str(item.get("observation", "")).strip(),
                )
                for item in raw.get("grounding_trace", [])
                if isinstance(item, dict)
            ],
            steps=[str(item).strip() for item in raw.get("steps", []) if str(item).strip()],
            success_criteria=[
                str(item).strip()
                for item in raw.get("success_criteria", [])
                if str(item).strip()
            ],
            constraints=[
                str(item).strip() for item in raw.get("constraints", []) if str(item).strip()
            ],
            memory_refs=[
                str(item).strip() for item in raw.get("memory_refs", []) if str(item).strip()
            ],
            journal_refs=[
                str(item).strip() for item in raw.get("journal_refs", []) if str(item).strip()
            ],
            revision_trace=trace,
        )
