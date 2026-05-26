from __future__ import annotations

from ...state import PresenceState
from ..interaction import PresenceInteraction
from .result import SleepResult


def apply_sleep(
    state: PresenceState,
    interaction: PresenceInteraction,
    *,
    session_id: str = "tao",
) -> SleepResult:
    """FSM 初始化转移：休眠 → 清空四维度自叙与交互态。"""
    state.affect.narrative = ""
    state.somatic.narrative = ""
    state.cognition.working_memory = ""
    state.cognition.thinking = ""
    state.perception.narrative = ""
    interaction.reset()
    return SleepResult(session_id=session_id, applied=True, reason="entered sleep window")
