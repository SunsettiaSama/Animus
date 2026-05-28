from __future__ import annotations

from agent.soul.memory.domain import ActivationCue
from agent.soul.memory.emergence.spread import SpreadActivationService


class SpeakEmergence:
    """??/???????????"""

    def __init__(
        self,
        spread: SpreadActivationService,
        *,
        use_point_query: bool = True,
    ) -> None:
        self._spread = spread
        self._use_point_query = use_point_query

    def trigger(
        self,
        *,
        session_id: str,
        interactor_id: str,
        user_text: str,
        agent_text: str = "",
    ) -> None:
        cue = ActivationCue(
            session_id=session_id,
            interactor_id=interactor_id or session_id,
            user_text=user_text,
            agent_text=agent_text,
        )
        if self._use_point_query:
            self._spread.query_point_async(cue)
        else:
            self._spread.expand_hot_async(cue)
