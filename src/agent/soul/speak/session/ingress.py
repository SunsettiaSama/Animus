from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.soul.speak.orchestrator.runtime.orchestrator_thread import OrchestratorThread


class SessionOrchestratorIngress:
    """session 入站事件转发到 orchestrator 调度线程。"""

    def __init__(self, orchestrator_thread: OrchestratorThread) -> None:
        self._thread = orchestrator_thread

    def notify_user_input(
        self,
        session_id: str,
        user_text: str,
        *,
        turn_index: int,
    ) -> None:
        self._thread.notify_user_input(
            session_id,
            user_text,
            turn_index=turn_index,
        )

    def notify_session_close(self, session_id: str) -> None:
        self._thread.notify_session_close(session_id)
