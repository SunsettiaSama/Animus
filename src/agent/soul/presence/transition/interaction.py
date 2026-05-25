from __future__ import annotations

from dataclasses import dataclass

from ..share_desire import ShareDesire
from .expectation import Expectation


@dataclass
class PresenceInteraction:
    """对话交互态：期待与分享冲动（非 FSM 维度）。"""

    expectation: Expectation = Expectation.none
    impulse_level: float = 0.0
    impulse_reason: str = ""
    impulse_source: str = ""
    share_desire: ShareDesire = ShareDesire.none

    def copy(self) -> PresenceInteraction:
        return PresenceInteraction(
            expectation=self.expectation,
            impulse_level=self.impulse_level,
            impulse_reason=self.impulse_reason,
            impulse_source=self.impulse_source,
            share_desire=self.share_desire,
        )

    def reset(self) -> None:
        self.expectation = Expectation.none
        self.impulse_level = 0.0
        self.impulse_reason = ""
        self.impulse_source = ""
        self.share_desire = ShareDesire.none

    def discharge_impulse(self, level: float) -> None:
        self.impulse_level = max(0.0, self.impulse_level - level)
        if self.impulse_level == 0.0:
            self.impulse_reason = ""
            self.impulse_source = ""
            self.share_desire = ShareDesire.none

    def to_dict(self) -> dict:
        return {
            "expectation": self.expectation.value,
            "impulse_level": self.impulse_level,
            "impulse_reason": self.impulse_reason,
            "impulse_source": self.impulse_source,
            "share_desire": self.share_desire.value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PresenceInteraction:
        return cls(
            expectation=Expectation(d.get("expectation", Expectation.none.value)),
            impulse_level=float(d.get("impulse_level", 0.0)),
            impulse_reason=str(d.get("impulse_reason", "")),
            impulse_source=str(d.get("impulse_source", "")),
            share_desire=ShareDesire(d.get("share_desire", ShareDesire.none.value)),
        )
