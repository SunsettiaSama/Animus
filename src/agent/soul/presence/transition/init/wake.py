from __future__ import annotations

from dataclasses import dataclass

from ...state import PresenceState
from ..interaction import PresenceInteraction
from .result import WakeResult


@dataclass
class WakeContext:
    agent_name: str = ""
    persona_summary: str = ""
    self_narrative: str = ""
    timezone: str = "Asia/Shanghai"


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
    )
