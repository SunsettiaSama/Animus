from __future__ import annotations

from dataclasses import dataclass

from ...expectation import Expectation


@dataclass
class BehaviorState:
    """行为与动作：对话期待、行动冲动与行为姿态。"""

    expectation: Expectation = Expectation.none
    impulse_level: float = 0.0
    impulse_reason: str = ""
    impulse_source: str = ""
    stance: str = ""
    readiness: float = 0.0

    def copy(self) -> BehaviorState:
        return BehaviorState(
            expectation=self.expectation,
            impulse_level=self.impulse_level,
            impulse_reason=self.impulse_reason,
            impulse_source=self.impulse_source,
            stance=self.stance,
            readiness=self.readiness,
        )

    def to_dict(self) -> dict:
        return {
            "expectation": self.expectation.value,
            "impulse_level": self.impulse_level,
            "impulse_reason": self.impulse_reason,
            "impulse_source": self.impulse_source,
            "stance": self.stance,
            "readiness": self.readiness,
        }

    @classmethod
    def from_dict(cls, d: dict) -> BehaviorState:
        return cls(
            expectation=Expectation(d.get("expectation", Expectation.none.value)),
            impulse_level=float(d.get("impulse_level", 0.0)),
            impulse_reason=str(d.get("impulse_reason", "")),
            impulse_source=str(d.get("impulse_source", "")),
            stance=str(d.get("stance", "")),
            readiness=float(d.get("readiness", 0.0)),
        )
