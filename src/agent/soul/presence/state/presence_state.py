from __future__ import annotations

from dataclasses import dataclass, field

from .static.affect import AffectState
from .static.cognition import CognitionState
from .static.perception import PerceptionState
from .static.somatic import SomaticState
from .dynamic.expectation.state import ExpectationState
from .lingering import LingeringMood, RecentExperiencePortrait

PRESENCE_DIMENSIONS: tuple[str, ...] = (
    "affect",
    "somatic",
    "cognition",
    "perception",
    "expectation",
)

_PRESENCE_LABELS: tuple[tuple[str, str], ...] = (
    ("affect", "情感"),
    ("somatic", "身体"),
    ("cognition", "认知"),
    ("perception", "感知"),
    ("expectation", "期待"),
)


@dataclass
class PresenceState:
    """当下态：四段静态自叙 + 动态期待驱动。"""

    affect: AffectState = field(default_factory=AffectState)
    somatic: SomaticState = field(default_factory=SomaticState)
    cognition: CognitionState = field(default_factory=CognitionState)
    perception: PerceptionState = field(default_factory=PerceptionState)
    expectation: ExpectationState = field(default_factory=ExpectationState)
    lingering_moods: list[LingeringMood] = field(default_factory=list)
    recent_portrait: RecentExperiencePortrait = field(
        default_factory=RecentExperiencePortrait,
    )

    def copy(self) -> PresenceState:
        return PresenceState(
            affect=self.affect.copy(),
            somatic=self.somatic.copy(),
            cognition=self.cognition.copy(),
            perception=self.perception.copy(),
            expectation=self.expectation.copy(),
            lingering_moods=[LingeringMood.from_dict(m.to_dict()) for m in self.lingering_moods],
            recent_portrait=RecentExperiencePortrait.from_dict(self.recent_portrait.to_dict()),
        )

    def reset_affect(self) -> None:
        self.affect = AffectState()

    def render(self) -> str:
        lines: list[str] = []
        for key, label in _PRESENCE_LABELS:
            text = getattr(self, key).render()
            if text:
                lines.append(f"**{label}** {text}")
        return "\n".join(lines)

    def is_empty(self) -> bool:
        narrative_empty = not any(
            getattr(self, key).render()
            for key, _ in _PRESENCE_LABELS
            if key != "expectation"
        )
        return narrative_empty and self.expectation.is_empty()

    def to_dict(self) -> dict:
        return {
            "affect": self.affect.to_dict(),
            "somatic": self.somatic.to_dict(),
            "cognition": self.cognition.to_dict(),
            "perception": self.perception.to_dict(),
            "expectation": self.expectation.to_dict(),
            "lingering_moods": [m.to_dict() for m in self.lingering_moods],
            "recent_portrait": self.recent_portrait.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> PresenceState:
        perception_raw = d.get("perception")
        if perception_raw is None and d.get("environment"):
            perception_raw = d.get("environment")
        portrait_raw = d.get("recent_portrait") or {}
        lingering_raw = d.get("lingering_moods") or []
        return cls(
            affect=AffectState.from_dict(d.get("affect") or {}),
            somatic=SomaticState.from_dict(d.get("somatic") or {}),
            cognition=CognitionState.from_dict(d.get("cognition") or {}),
            perception=PerceptionState.from_dict(perception_raw or {}),
            expectation=ExpectationState.from_dict(d.get("expectation") or {}),
            lingering_moods=[LingeringMood.from_dict(x) for x in lingering_raw],
            recent_portrait=RecentExperiencePortrait.from_dict(portrait_raw),
        )


@dataclass(frozen=True)
class PresenceContext:
    """单次 Presence 事件的附加上下文（不持久化）。

    ``line_open``：由 ``PresenceService`` 根据 ``Expectation`` 在网关侧推导，
    与 ``agent.posture`` FSM 无运行时耦合（命名沿用早期分层概念）。
    """

    line_open: bool = False
    proactive_intent_id: str = ""
