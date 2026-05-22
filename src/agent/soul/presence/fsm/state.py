from __future__ import annotations

from dataclasses import dataclass, field

from ..expectation import Expectation
from ..share_desire import ShareDesire
from .affect import AffectState
from .behavior import BehaviorState
from .cognition import CognitionState
from .environment import EnvironmentState
from .motivation import MotivationState
from .somatic import SomaticState
from .temporality import TemporalityState

PRESENCE_DIMENSIONS: tuple[str, ...] = (
    "somatic",
    "affect",
    "cognition",
    "behavior",
    "environment",
    "motivation",
    "temporality",
)


@dataclass
class PresenceState:
    """当下态 FSM 完整状态：七个维度子状态为唯一字段入口。"""

    somatic: SomaticState = field(default_factory=SomaticState)
    affect: AffectState = field(default_factory=AffectState)
    cognition: CognitionState = field(default_factory=CognitionState)
    behavior: BehaviorState = field(default_factory=BehaviorState)
    environment: EnvironmentState = field(default_factory=EnvironmentState)
    motivation: MotivationState = field(default_factory=MotivationState)
    temporality: TemporalityState = field(default_factory=TemporalityState)

    def copy(self) -> PresenceState:
        return PresenceState(
            somatic=self.somatic.copy(),
            affect=self.affect.copy(),
            cognition=self.cognition.copy(),
            behavior=self.behavior.copy(),
            environment=self.environment.copy(),
            motivation=self.motivation.copy(),
            temporality=self.temporality.copy(),
        )

    def reset(self) -> None:
        """重置对话行为层与动机层中的瞬时交互字段。"""
        self.behavior.expectation = Expectation.none
        self.behavior.impulse_level = 0.0
        self.behavior.impulse_reason = ""
        self.behavior.impulse_source = ""
        self.motivation.share_desire = ShareDesire.none

    def reset_affect(self) -> None:
        self.affect = AffectState()

    def discharge_impulse(self, amount: float) -> None:
        self.behavior.impulse_level = max(0.0, self.behavior.impulse_level - amount)

    def to_dict(self) -> dict:
        return {
            "somatic": self.somatic.to_dict(),
            "affect": self.affect.to_dict(),
            "cognition": self.cognition.to_dict(),
            "behavior": self.behavior.to_dict(),
            "environment": self.environment.to_dict(),
            "motivation": self.motivation.to_dict(),
            "temporality": self.temporality.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> PresenceState:
        if "behavior" in d or "motivation" in d or "somatic" in d:
            return cls(
                somatic=SomaticState.from_dict(d.get("somatic") or {}),
                affect=AffectState.from_dict(d.get("affect") or {}),
                cognition=CognitionState.from_dict(d.get("cognition") or {}),
                behavior=BehaviorState.from_dict(d.get("behavior") or {}),
                environment=EnvironmentState.from_dict(d.get("environment") or {}),
                motivation=MotivationState.from_dict(d.get("motivation") or {}),
                temporality=TemporalityState.from_dict(d.get("temporality") or {}),
            )
        return cls(
            behavior=BehaviorState.from_dict(d),
            motivation=MotivationState.from_dict(d),
            affect=AffectState.from_dict(d.get("affect") or {}),
        )


@dataclass(frozen=True)
class PresenceContext:
    """对话结构上下文（来自 posture，不持久化）。"""

    line_open: bool = False
    proactive_intent_id: str = ""
