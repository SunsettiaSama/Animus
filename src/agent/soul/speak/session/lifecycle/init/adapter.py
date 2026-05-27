from __future__ import annotations

from ..types import SessionLifecyclePort, SessionOpenTrigger


class SpeakSessionLifecycleAdapter:
    """Speak 会话 rotate 时同步清空 compose/context，并委托 Soul 层 lifecycle。"""

    def __init__(
        self,
        *,
        reset_context,
        inner: SessionLifecyclePort | None = None,
    ) -> None:
        self._reset_context = reset_context
        self._inner = inner

    def close_dialogue_interaction(self, session_id: str) -> dict:
        self._reset_context(session_id)
        if self._inner is None:
            return {"ok": True, "session_id": session_id, "ingested": False}
        return self._inner.close_dialogue_interaction(session_id)

    def start_dialogue_session(
        self,
        session_id: str,
        *,
        trigger: SessionOpenTrigger = "user_message",
    ) -> dict:
        if self._inner is None:
            return {"ok": True, "session_id": session_id, "trigger": trigger}
        return self._inner.start_dialogue_session(session_id, trigger=trigger)

    def open_proactive_outbound(
        self,
        session_id: str,
        message: str,
        *,
        proactive_intent_id: str = "",
    ) -> dict:
        if self._inner is None:
            return {
                "ok": True,
                "session_id": session_id,
                "message": message,
                "proactive_intent_id": proactive_intent_id,
            }
        return self._inner.open_proactive_outbound(
            session_id,
            message,
            proactive_intent_id=proactive_intent_id,
        )
