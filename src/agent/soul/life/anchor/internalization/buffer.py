from __future__ import annotations

from agent.soul.life.experience.anchor_codec import InteractionDirection

from .session import InteractionSession


class InteractionBuffer:
    """按 session_id 持有进行中的现实相遇。"""

    def __init__(self) -> None:
        self._sessions: dict[str, InteractionSession] = {}

    def get(self, session_id: str) -> InteractionSession | None:
        return self._sessions.get(session_id)

    def open(
        self,
        session_id: str,
        direction: InteractionDirection,
        *,
        proactive_intent_id: str = "",
        outbound_message: str = "",
        outbound_reason: str = "",
    ) -> InteractionSession:
        existing = self._sessions.get(session_id)
        if existing is not None:
            if proactive_intent_id and not existing.proactive_intent_id:
                existing.proactive_intent_id = proactive_intent_id
            if outbound_message.strip() and not existing.outbound_message:
                existing.outbound_message = outbound_message.strip()
                existing.outbound_reason = outbound_reason.strip()
            existing.touch()
            return existing
        session = InteractionSession(
            session_id=session_id,
            direction=direction,
            proactive_intent_id=proactive_intent_id,
            outbound_message=outbound_message.strip(),
            outbound_reason=outbound_reason.strip(),
        )
        self._sessions[session_id] = session
        return session

    def pop(self, session_id: str) -> InteractionSession | None:
        return self._sessions.pop(session_id, None)

    def active_session_ids(self) -> list[str]:
        return list(self._sessions.keys())
