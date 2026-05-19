from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


class VirtualChronicleKind(str, Enum):
    """虚拟生命账本条目类型。"""

    story_beat = "story_beat"
    landmark = "landmark"
    surprise = "surprise"
    wander_beat = "wander_beat"
    collision = "collision"


@dataclass
class VirtualChronicleEntry:
    """虚拟层客观记录：地标、意外、漫游叙事等虚构体验的事实摘要。"""

    kind: VirtualChronicleKind
    summary: str
    id: str = field(default_factory=_uid)
    ts: str = field(default_factory=_now_iso)
    experience_id: str = ""
    trigger: str = ""
    landmark_id: str = ""
    dice_value: int = 0
    dice_tendency: str = ""
    emotion_label: str = ""
    salience: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ts": self.ts,
            "kind": self.kind.value,
            "summary": self.summary,
            "experience_id": self.experience_id,
            "trigger": self.trigger,
            "landmark_id": self.landmark_id,
            "dice_value": self.dice_value,
            "dice_tendency": self.dice_tendency,
            "emotion_label": self.emotion_label,
            "salience": self.salience,
        }

    @classmethod
    def from_dict(cls, d: dict) -> VirtualChronicleEntry:
        return cls(
            id=d.get("id", _uid()),
            ts=d.get("ts", _now_iso()),
            kind=VirtualChronicleKind(d["kind"]),
            summary=d.get("summary", ""),
            experience_id=d.get("experience_id", ""),
            trigger=d.get("trigger", ""),
            landmark_id=d.get("landmark_id", ""),
            dice_value=int(d.get("dice_value", 0)),
            dice_tendency=d.get("dice_tendency", ""),
            emotion_label=d.get("emotion_label", ""),
            salience=float(d.get("salience", 0.0)),
        )
