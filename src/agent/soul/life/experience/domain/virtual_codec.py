from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .unit import ExperienceUnit

_CTX_PREFIX = "__vctx:"


class VirtualUnitTrigger(str, Enum):
    """虚拟层产生 ExperienceUnit 时的触发类型。"""

    landmark = "landmark"
    landmark_agenda = "landmark_agenda"
    landmark_plan = "landmark_plan"
    surprise = "surprise"
    wander = "wander"
    fabricate = "fabricate"


@dataclass(frozen=True)
class VirtualUnitContext:
    """虚拟层 → 编排器：写入 unit 时必须附带的上下文（编码于 prior_thought）。"""

    trigger: VirtualUnitTrigger
    landmark_id: str = ""
    dice_value: int = 0
    dice_tendency: str = ""
    story_event_id: str = ""
    scene_id: str = ""
    question_id: str = ""

    def to_dict(self) -> dict:
        return {
            "trigger": self.trigger.value,
            "landmark_id": self.landmark_id,
            "dice_value": self.dice_value,
            "dice_tendency": self.dice_tendency,
            "story_event_id": self.story_event_id,
            "scene_id": self.scene_id,
            "question_id": self.question_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> VirtualUnitContext:
        return cls(
            trigger=VirtualUnitTrigger(d.get("trigger", VirtualUnitTrigger.fabricate.value)),
            landmark_id=str(d.get("landmark_id", "")),
            dice_value=int(d.get("dice_value", 0)),
            dice_tendency=str(d.get("dice_tendency", "")),
            story_event_id=str(d.get("story_event_id", "")),
            scene_id=str(d.get("scene_id", "")),
            question_id=str(d.get("question_id", "")),
        )


def stamp_virtual_context(unit: ExperienceUnit, ctx: VirtualUnitContext) -> None:
    unit.situation.prior_thought = _CTX_PREFIX + json.dumps(
        ctx.to_dict(), ensure_ascii=False
    )


def read_virtual_context(unit: ExperienceUnit) -> VirtualUnitContext | None:
    raw = (unit.situation.prior_thought or "").strip()
    if raw.startswith("__pbx:"):
        bundle = json.loads(raw[len("__pbx:"):])
        raw = str(bundle.get("prior_thought", "")).strip()
    if not raw.startswith(_CTX_PREFIX):
        return None
    payload = json.loads(raw[len(_CTX_PREFIX):])
    return VirtualUnitContext.from_dict(payload)
