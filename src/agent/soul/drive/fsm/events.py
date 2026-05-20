from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DriveEventKind(str, Enum):
    user_text = "user_text"
    agent_utterance = "agent_utterance"
    agent_deferred = "agent_deferred"
    scene_enter = "scene_enter"
    proactive_open = "proactive_open"
    proactive_delivered = "proactive_delivered"
    ambiguity_detected = "ambiguity_detected"
    clarify_resolved = "clarify_resolved"
    close = "close"


@dataclass(frozen=True)
class DriveEvent:
    kind: DriveEventKind
    session_id: str
    payload: dict = field(default_factory=dict)

    @staticmethod
    def user_text(
        session_id: str,
        *,
        ambiguous: bool = False,
        resolves_clarify: bool = False,
        proactive_intent_id: str = "",
    ) -> DriveEvent:
        return DriveEvent(
            DriveEventKind.user_text,
            session_id,
            {
                "ambiguous": ambiguous,
                "resolves_clarify": resolves_clarify,
                "proactive_intent_id": proactive_intent_id,
            },
        )

    @staticmethod
    def agent_utterance(
        session_id: str,
        *,
        has_question: bool = False,
        final: bool = False,
        notify_only: bool = False,
    ) -> DriveEvent:
        return DriveEvent(
            DriveEventKind.agent_utterance,
            session_id,
            {
                "has_question": has_question,
                "final": final,
                "notify_only": notify_only,
            },
        )

    @staticmethod
    def agent_deferred(session_id: str) -> DriveEvent:
        return DriveEvent(DriveEventKind.agent_deferred, session_id)

    @staticmethod
    def scene_enter(session_id: str) -> DriveEvent:
        return DriveEvent(DriveEventKind.scene_enter, session_id)

    @staticmethod
    def proactive_open(
        session_id: str,
        *,
        wait_reply: bool = True,
    ) -> DriveEvent:
        return DriveEvent(
            DriveEventKind.proactive_open,
            session_id,
            {"wait_reply": wait_reply},
        )

    @staticmethod
    def proactive_delivered(session_id: str) -> DriveEvent:
        return DriveEvent(DriveEventKind.proactive_delivered, session_id)

    @staticmethod
    def ambiguity_detected(session_id: str, reason: str = "") -> DriveEvent:
        return DriveEvent(
            DriveEventKind.ambiguity_detected,
            session_id,
            {"reason": reason},
        )

    @staticmethod
    def clarify_resolved(session_id: str) -> DriveEvent:
        return DriveEvent(DriveEventKind.clarify_resolved, session_id)

    @staticmethod
    def close(session_id: str, reason: str = "") -> DriveEvent:
        return DriveEvent(
            DriveEventKind.close,
            session_id,
            {"reason": reason},
        )
