from __future__ import annotations

from dataclasses import dataclass

from ..expectation import Expectation
from ..share_desire import ShareDesire


@dataclass
class DriveState:
    """Drive FSM 完整状态：期待 + 交互冲动。"""

    expectation: Expectation = Expectation.none
    impulse_level: float = 0.0
    impulse_reason: str = ""
    impulse_source: str = ""
    share_desire: ShareDesire = ShareDesire.none

    def copy(self) -> DriveState:
        return DriveState(
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

    def discharge_impulse(self, amount: float) -> None:
        self.impulse_level = max(0.0, self.impulse_level - amount)


@dataclass(frozen=True)
class DriveContext:
    """对话结构上下文（来自 posture，不持久化）。"""

    line_open: bool = False
    proactive_intent_id: str = ""
