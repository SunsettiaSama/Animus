from __future__ import annotations

from ..state.presence_state import PresenceState
from .prose import clamp_chars, validate_agent_prose

_DEFAULT_MAX = 350


def render_recent_portrait_for_agent(
    state: PresenceState | None,
    *,
    max_chars: int = _DEFAULT_MAX,
) -> str:
    if state is None:
        return ""
    narrative = state.recent_portrait.narrative.strip()
    if not narrative:
        return ""
    return clamp_chars(narrative, max_chars)
