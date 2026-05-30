from __future__ import annotations

from agent.soul.memory.domain import ActivationCue

from ..deps import SessionIODeps
from ..request import DialogueTurnInbound


def schedule_dynamic_event(deps: SessionIODeps, inbound: DialogueTurnInbound) -> None:
    """对话轮次实时事件记忆：委托 emergence 点检索（SpreadActivationService）。"""
    cue = ActivationCue(
        session_id=inbound.session_id.strip(),
        interactor_id=inbound.interactor_id.strip(),
        user_text=inbound.user_text.strip(),
        agent_text=inbound.agent_text.strip(),
        turn_index=inbound.turn_index,
    )
    deps.emergence.query_point_async(cue)
