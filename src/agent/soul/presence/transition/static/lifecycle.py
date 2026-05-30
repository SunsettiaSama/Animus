from __future__ import annotations

from dataclasses import dataclass, field

from ...state import PresenceState
from ..interaction import PresenceInteraction


@dataclass
class WakeContext:
    agent_name: str = ""
    persona_summary: str = ""
    self_narrative: str = ""
    timezone: str = "Asia/Shanghai"


@dataclass
class WakeResult:
    session_id: str
    applied: bool = True
    source: str = ""
    reason: str = ""
    narratives: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.narratives is None:
            self.narratives = {}
        if self.notes is None:
            self.notes = []


@dataclass
class SleepResult:
    session_id: str
    applied: bool = True
    reason: str = ""


def apply_wake(
    state: PresenceState,
    interaction: PresenceInteraction,
    *,
    session_id: str = "tao",
    context: WakeContext | None = None,
) -> WakeResult:
    _ = state
    _ = context
    interaction.reset()
    return WakeResult(
        session_id=session_id,
        applied=True,
        source="lifecycle",
        reason="awake",
        notes=[],
    )


def apply_sleep(
    state: PresenceState,
    interaction: PresenceInteraction,
    *,
    session_id: str = "tao",
) -> SleepResult:
    state.affect.narrative = ""
    state.somatic.narrative = ""
    state.cognition.working_memory = ""
    state.cognition.thinking = ""
    state.perception.narrative = ""
    interaction.reset()
    return SleepResult(session_id=session_id, applied=True, reason="entered sleep window")


def apply_dialogue_session_boundary(state: PresenceState) -> list[str]:
    """Speak session rotate：裁剪对话型静态字段，避免 verbatim 跨 generation 注入。"""
    from ...state.static import compose_narrative, normalize_narrative

    notes: list[str] = []
    perception = normalize_narrative(state.perception.narrative)
    if perception:
        existing = normalize_narrative(state.cognition.thinking)
        folded = perception[:240]
        state.cognition.thinking = compose_narrative(existing, folded) if existing else folded
        notes.append("boundary: perception folded into thinking")
    state.perception.narrative = ""
    state.cognition.working_memory = ""
    notes.append("boundary: cleared perception + working_memory")
    return notes
