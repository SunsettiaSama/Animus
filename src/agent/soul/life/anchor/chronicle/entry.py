from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


class AnchorChronicleKind(str, Enum):
    """锚点层 Chronicle 条目类型（现实交互）。"""

    user_turn = "user_turn"
    interaction_open = "interaction_open"
    interaction_close = "interaction_close"
    collision = "collision"
    scheduler_digest = "scheduler_digest"


ChronicleKind = AnchorChronicleKind


@dataclass
class AnchorChronicleEntry:
    """锚点层客观事实记录：用户对话、调度摘要、现实侧交会。"""

    kind: AnchorChronicleKind
    summary: str
    id: str = field(default_factory=_uid)
    ts: str = field(default_factory=_now_iso)
    session_id: str = ""
    turn_index: int = 0
    emotion_label: str = ""
    salience: float = 0.0
    experience_id: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ts": self.ts,
            "kind": self.kind.value,
            "summary": self.summary,
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "emotion_label": self.emotion_label,
            "salience": self.salience,
            "experience_id": self.experience_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AnchorChronicleEntry:
        return cls(
            id=d.get("id", _uid()),
            ts=d.get("ts", _now_iso()),
            kind=AnchorChronicleKind(d["kind"]),
            summary=d.get("summary", ""),
            session_id=d.get("session_id", ""),
            turn_index=int(d.get("turn_index", 0)),
            emotion_label=d.get("emotion_label", ""),
            salience=float(d.get("salience", 0.0)),
            experience_id=d.get("experience_id", ""),
        )


ChronicleEntry = AnchorChronicleEntry
