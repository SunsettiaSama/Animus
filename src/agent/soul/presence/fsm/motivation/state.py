from __future__ import annotations

from dataclasses import dataclass

from ...share_desire import ShareDesire


@dataclass
class MotivationState:
    """动机与意愿：分享冲动、主导意图与紧迫度。"""

    share_desire: ShareDesire = ShareDesire.none
    intent: str = ""
    urgency: float = 0.0
    label: str = ""

    def copy(self) -> MotivationState:
        return MotivationState(
            share_desire=self.share_desire,
            intent=self.intent,
            urgency=self.urgency,
            label=self.label,
        )

    def to_dict(self) -> dict:
        return {
            "share_desire": self.share_desire.value,
            "intent": self.intent,
            "urgency": self.urgency,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MotivationState:
        return cls(
            share_desire=ShareDesire(d.get("share_desire", ShareDesire.none.value)),
            intent=str(d.get("intent", "")),
            urgency=float(d.get("urgency", 0.0)),
            label=str(d.get("label", "")),
        )
