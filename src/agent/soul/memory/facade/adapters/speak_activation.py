from __future__ import annotations

from agent.soul.memory.activation.service import ActivationService
from agent.soul.memory.domain import ActivationCue


class SpeakActivationAdapter:
    def __init__(self, activation: ActivationService) -> None:
        self._activation = activation

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
        self._activation.activate_async(cue)
