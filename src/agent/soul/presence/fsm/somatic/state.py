from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SomaticState:
    """生理与身体状态：活力、唤醒与身体感受。"""

    vitality: float = 0.5
    arousal: float = 0.5
    fatigue: float = 0.0
    tension: float = 0.0
    sensation: str = ""

    def copy(self) -> SomaticState:
        return SomaticState(
            vitality=self.vitality,
            arousal=self.arousal,
            fatigue=self.fatigue,
            tension=self.tension,
            sensation=self.sensation,
        )

    def to_dict(self) -> dict:
        return {
            "vitality": self.vitality,
            "arousal": self.arousal,
            "fatigue": self.fatigue,
            "tension": self.tension,
            "sensation": self.sensation,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SomaticState:
        return cls(
            vitality=float(d.get("vitality", 0.5)),
            arousal=float(d.get("arousal", 0.5)),
            fatigue=float(d.get("fatigue", 0.0)),
            tension=float(d.get("tension", 0.0)),
            sensation=str(d.get("sensation", "")),
        )
