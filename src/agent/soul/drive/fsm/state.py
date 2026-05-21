from __future__ import annotations

from dataclasses import dataclass, field

from ..affect import AffectState
from ..expectation import Expectation
from ..share_desire import ShareDesire


@dataclass
class DriveState:
    """Drive FSM 完整状态：期待 + 交互冲动 + 附属情绪（affect）。"""

    expectation: Expectation = Expectation.none
    impulse_level: float = 0.0
    impulse_reason: str = ""
    impulse_source: str = ""
    share_desire: ShareDesire = ShareDesire.none
    affect: AffectState = field(default_factory=AffectState)

    def copy(self) -> DriveState:
        return DriveState(
            expectation=self.expectation,
            impulse_level=self.impulse_level,
            impulse_reason=self.impulse_reason,
            impulse_source=self.impulse_source,
            share_desire=self.share_desire,
            affect=self.affect.copy(),
        )

    def reset(self) -> None:
        self.expectation = Expectation.none
        self.impulse_level = 0.0
        self.impulse_reason = ""
        self.impulse_source = ""
        self.share_desire = ShareDesire.none

    def reset_affect(self) -> None:
        self.affect = AffectState()

    def discharge_impulse(self, amount: float) -> None:
        self.impulse_level = max(0.0, self.impulse_level - amount)

    def to_dict(self) -> dict:
        return {
            "expectation": self.expectation.value,
            "impulse_level": self.impulse_level,
            "impulse_reason": self.impulse_reason,
            "impulse_source": self.impulse_source,
            "share_desire": self.share_desire.value,
            "affect": self.affect.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> DriveState:
        return cls(
            expectation=Expectation(d.get("expectation", Expectation.none.value)),
            impulse_level=float(d.get("impulse_level", 0.0)),
            impulse_reason=str(d.get("impulse_reason", "")),
            impulse_source=str(d.get("impulse_source", "")),
            share_desire=ShareDesire(d.get("share_desire", ShareDesire.none.value)),
            affect=AffectState.from_dict(d.get("affect") or {}),
        )


@dataclass(frozen=True)
class DriveContext:
    """对话结构上下文（来自 posture，不持久化）。"""

    line_open: bool = False
    proactive_intent_id: str = ""
