from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agent.soul.speak.session.queue import InterruptContext, UserInputItem
from agent.soul.speak.session.service import SpeakSessionService
from agent.soul.speak.session.turn import SessionTurnHost, run_session_turn


@dataclass
class LegacyQAPipelineRunner:
    manager: SpeakSessionService
    host: SessionTurnHost
    interrupt_context_for: Callable[[str, UserInputItem], InterruptContext | None]

    def run(self, item: UserInputItem):
        interrupt_context = None
        if item.interrupted:
            interrupt_context = self.interrupt_context_for(item.session_id, item)
        result = run_session_turn(
            self.manager,
            self.host,
            item.session_id,
            item.user_text,
            stream=item.stream,
            mode=item.mode,
            record=item.record,
            interrupt_context=interrupt_context,
        )
        result.meta["pipeline"] = "legacy_qa"
        if "pipeline: legacy_qa" not in result.notes:
            result.notes.append("pipeline: legacy_qa")
        return result
